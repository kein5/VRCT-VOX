"""Generation controls must never alter text/OSC or silently disappear."""

from threading import Event, Thread

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.speechcpp_tts import CancelToken, SpeechCppTTS, SpeechError
from models.tts.tts_scheduler import VoiceEventBus
from test_scheduler import Sink as Sink, event as event, until as until
from test_controller_integration import controller_module as controller_module

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['controller_module']


def card(*, seed=True, instructions=True, maximum=9007199254740991):
    options = []
    if seed:
        options.append(dict(name="seed", type="int", minimum=0, maximum=maximum))
    if instructions:
        options.append(dict(name="instructions", type="string"))
    return {
        "data": [
            {"id": "tts-test", "speech": {"task": "synthesis", "options": options}}
        ]
    }


@pytest.mark.parametrize(
    "bad", ["-1", "1.5", "1e2", "9007199254740992", True, 42, "１２", "1\x00"]
)
def test_invalid_seed_settings_rejected(bad):
    with pytest.raises(ValueError):
        VoiceSettings.from_dict({"japanese_seed": bad})


def test_options_roundtrip_zero_maximum_and_language_selection():
    settings = VoiceSettings.from_dict(
        dict(
            japanese_seed="0",
            multilingual_seed="9007199254740991",
            japanese_instructions="やさしく\n落ち着いて。",
            multilingual_instructions="Speak clearly.",
        )
    )
    assert VoiceSettings.from_dict(settings.to_dict()) == settings
    assert settings.options_for("Japanese") == {
        "seed": 0,
        "instructions": "やさしく\n落ち着いて。",
    }
    assert settings.options_for("en") == {
        "seed": 9007199254740991,
        "instructions": "Speak clearly.",
    }
    assert VoiceSettings.from_dict({}).options_for("ja") == {}


@pytest.mark.parametrize(
    "bad",
    ["x" * 4001, "\x00", "private\x1btext", True],
    ids=["too-long", "nul", "escape", "bool"],
)
def test_invalid_instruction_rejected(bad):
    with pytest.raises(ValueError):
        VoiceSettings.from_dict({"multilingual_instructions": bad})


def test_instruction_limit_and_newlines_are_preserved():
    value = "声\n" * 2000
    assert VoiceSettings.from_dict({"japanese_instructions": value}).options_for(
        "ja"
    ) == {"instructions": value}


def test_post_sends_zero_and_instruction_separately_and_basic_mode_skips_catalog(
    pcm_server,
):
    gets = []
    with pcm_server(model_document=card(), before_get=gets.append) as (url, requests):
        provider = SpeechCppTTS(url)
        list(
            provider.synthesize_stream(
                "本文",
                "none",
                "ja",
                CancelToken(),
                seed=0,
                instructions="ゆっくり\n話す",
            )
        )
        assert requests == [
            (
                "/v1/audio/speech",
                dict(
                    input="本文",
                    voice="none",
                    language="ja",
                    response_format="pcm",
                    seed=0,
                    instructions="ゆっくり\n話す",
                ),
            )
        ]
        assert gets == ["/v1/models"]
        list(provider.synthesize_stream("次", "none", "ja", CancelToken()))
        assert len(gets) == 1
        assert requests[-1][1] == dict(
            input="次", voice="none", language="ja", response_format="pcm"
        )


@pytest.mark.parametrize(
    "document,kwargs,code",
    [
        (
            card(instructions=False),
            {"instructions": "private phrase"},
            "tts_instructions_unsupported",
        ),
        (card(seed=False), {"seed": 1}, "tts_seed_unsupported"),
        (card(maximum=42), {"seed": 43}, "tts_seed_out_of_range"),
        ({"data": []}, {"seed": 0}, "tts_model_options_unavailable"),
    ],
)
def test_unsupported_or_unknown_options_never_post(document, kwargs, code, pcm_server):
    with pcm_server(model_document=document) as (url, requests):
        with pytest.raises(SpeechError, match="^" + code + "$"):
            list(
                SpeechCppTTS(url).synthesize_stream(
                    "private text", "none", "ja", CancelToken(), **kwargs
                )
            )
        assert not requests


def test_model_change_rechecks_capability_before_next_generation(pcm_server):
    document = card()
    with pcm_server(model_document=document) as (url, requests):
        provider = SpeechCppTTS(url)
        list(
            provider.synthesize_stream(
                "one", "none", "ja", CancelToken(), instructions="softly"
            )
        )
        document["data"] = card(instructions=False)["data"]
        with pytest.raises(SpeechError, match="tts_instructions_unsupported"):
            list(
                provider.synthesize_stream(
                    "two", "none", "ja", CancelToken(), instructions="softly"
                )
            )
        assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not-json-private-path",
        b"x" * 65537,
        b'{"data":[{"id":"tts","speech":{"task":"synthesis","options":null}}]}',
    ],
    ids=["invalid-json", "too-large", "invalid-options"],
)
def test_bounded_catalog_rejects_bad_documents(body, pcm_server):
    with pcm_server(models_body=body) as (url, _):
        with pytest.raises(SpeechError, match="^tts_model_options_unavailable$"):
            SpeechCppTTS(url).get_model_options()


def test_catalog_timeout_and_cancel_interrupt_before_audio(pcm_server):
    entered, release = Event(), Event()

    def block(path):
        entered.set()
        release.wait(2)

    with pcm_server(model_document=card(), before_get=block) as (url, requests):
        token = CancelToken()
        result = []

        def work():
            try:
                list(
                    SpeechCppTTS(url).synthesize_stream(
                        "text", "none", "ja", token, seed=0
                    )
                )
            except SpeechError as exc:
                result.append(str(exc))

        thread = Thread(target=work)
        thread.start()
        try:
            assert entered.wait(1)
            token.cancel()
            thread.join(0.5)
            assert not thread.is_alive()
            assert result == ["cancelled"] and not requests
        finally:
            release.set()
            thread.join(2)


def test_catalog_timeout_is_safe_and_never_posts(pcm_server):
    from time import sleep

    with pcm_server(model_document=card(), before_get=lambda path: sleep(0.15)) as (
        url,
        requests,
    ):
        with pytest.raises(SpeechError, match="^tts_model_options_unavailable$"):
            SpeechCppTTS(url, timeout=0.03).get_model_options()
        assert not requests


def test_ambiguous_or_invalid_capability_is_not_treated_as_supported(pcm_server):
    document = card()
    document["data"].append(card()["data"][0])
    with pcm_server(model_document=document) as (url, _):
        with pytest.raises(SpeechError, match="tts_model_options_unavailable"):
            SpeechCppTTS(url).get_model_options()


def test_old_bundled_catalog_response_is_discarded_after_server_restart(
    controller_module, monkeypatch, pcm_server
):
    from unittest.mock import Mock
    from types import SimpleNamespace

    entered, release = Event(), Event()

    def wait(path):
        entered.set()
        release.wait(2)

    c = controller_module.Controller()
    generation = {"japanese": {"generation": 1}}
    c.speech_servers = SimpleNamespace(state=lambda: generation, binding=Mock())
    c.setVoiceSettings({"japanese_server": "bundled"})
    result = []
    with pcm_server(model_document=card(), before_get=wait) as (url, _):
        c.speech_servers.binding.return_value = url
        worker = Thread(
            target=lambda: result.append(c.getTtsModelOptions({"role": "japanese"}))
        )
        worker.start()
        try:
            assert entered.wait(1)
            generation["japanese"]["generation"] = 2
            release.set()
            worker.join(2)
            assert result[0]["result"]["options"] is None
            assert result[0]["result"]["error_code"] == "tts_state_changed"
            assert result[0]["result"]["server_generation"] == 1
        finally:
            release.set()
            worker.join(2)
            c.voice_route.close()
            c.voice_events.close()


def test_mic_translation_uses_target_language_generation_options(pcm_server):
    with pcm_server(model_document=card()) as (url, requests):
        settings = VoiceSettings.from_dict(
            dict(
                mic_mode="translated",
                direct_policy="mix",
                output_device="cable",
                multilingual_url=url,
                japanese_seed="1",
                multilingual_seed="2",
                japanese_instructions="日本語用",
                multilingual_instructions="English style",
            )
        )
        sink = Sink()
        bus = VoiceEventBus(settings, router=AudioRouter(lambda *a: sink))
        try:
            assert bus.publish(
                event(
                    "mic",
                    source="mic",
                    translated_text="hello",
                    target_language="English",
                )
            )
            until(lambda: bus.status()["completed"] == 1)
            assert requests[0][1]["seed"] == 2
            assert requests[0][1]["instructions"] == "English style"
            assert requests[0][1]["input"] == "hello"
        finally:
            bus.close()


def test_controller_returns_catalog_identity_and_does_not_change_settings(
    controller_module, pcm_server
):
    c = controller_module.Controller()
    with pcm_server(model_document=card()) as (url, requests):
        try:
            c.setVoiceSettings(
                dict(
                    japanese_url=url, japanese_seed="42", japanese_instructions="softly"
                )
            )
            state = c.getTtsModelOptions({"role": "japanese"})
            assert state["status"] == 200
            row = state["result"]
            assert (
                row["role"] == "japanese"
                and row["configured_url"] == url
                and row["server"] == "external"
            )
            assert row["server_generation"] is None
            assert row["options"]["model"] == "tts-test"
            assert row["options"]["seed"] == {"minimum": 0, "maximum": 9007199254740991}
            assert row["options"]["instructions"] is True
            assert c.voice_events.settings.japanese_instructions == "softly"
            assert not requests and not c.voice_events.status()["tts_enabled"]
        finally:
            c.voice_route.close()
            c.voice_events.close()


def test_instruction_is_kept_in_ipc_but_redacted_from_diagnostic_logs(monkeypatch):
    import base64
    import json
    from unittest.mock import Mock
    import utils

    logger = Mock()
    lines = []
    monkeypatch.setattr(utils, "process_logger", logger)
    monkeypatch.setattr(utils, "_enqueueLogLine", lines.append)
    monkeypatch.setattr(utils, "_enqueueResponseLine", lines.append)
    settings = {"japanese_instructions": "PRIVATE STYLE", "japanese_seed": "42"}
    encoded = base64.b64encode(json.dumps(settings).encode()).decode()
    utils.printLog("/set/data/voice_settings", {"receive_data": encoded})
    utils.printResponse(200, "/get/data/voice_settings", settings)
    utils.printResponse(
        200, "/run/initialization_complete", {"/get/data/voice_settings": settings}
    )
    diagnostics = str(logger.info.call_args_list)
    assert "PRIVATE STYLE" not in diagnostics and encoded not in diagnostics
    assert "PRIVATE STYLE" not in lines[0] and encoded not in lines[0]
    assert json.loads(lines[1])["result"] == settings


def test_catalog_request_id_is_echoed_without_changing_options(
    controller_module, pcm_server
):
    c = controller_module.Controller()
    with pcm_server(model_document=card()) as (url, _):
        try:
            c.setVoiceSettings(dict(japanese_url=url))
            response = c.getTtsModelOptions(
                {"role": "japanese", "request_id": "page-17"}
            )
            assert response["status"] == 200
            assert response["result"]["request_id"] == "page-17"
            assert response["result"]["options"]["seed"]["minimum"] == 0
            for invalid in ("", "x" * 65, 1, None, "bad\nvalue"):
                assert (
                    c.getTtsModelOptions({"role": "japanese", "request_id": invalid})[
                        "status"
                    ]
                    == 400
                )
        finally:
            c.voice_route.close()
            c.voice_events.close()
