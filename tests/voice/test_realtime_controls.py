"""Real Controller and receiver; capture/translation are injected, never recorded."""

import copy
from queue import Queue
from threading import Event, Thread
import time
from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest

from models.transcription.realtime_settings import normalize_settings
from test_controller_integration import controller_module  # noqa: F401
from test_priority_cancel import mainloop_module, wire_message  # noqa: F401
from test_realtime_delivery import Session, eventually


def settings():
    # Explicit languages: "auto" (the fresh speaker default) has its own tests.
    value = normalize_settings({"model": "asr", "speaker": {"language": "ja"}})
    for source, media in (("mic", "Audio/Source"), ("speaker", "Audio/Sink")):
        value[source]["endpoint"] = dict(
            cookie="1", serial="2", name=source, media_class=media
        )
    return value


class CaptureSession(Session):
    created = None

    def __init__(self, source, options, endpoint):
        super().__init__()
        self.source, self.options, self.endpoint = source, options, endpoint
        self.namespace = uuid4().hex
        self.active = False
        self.busy = False
        self.created.append(self)

    def start(self):
        self.active = True

    def close(self, timeout=3):
        self.request_stop()
        return not self.busy


@pytest.fixture
def app(controller_module, monkeypatch):  # noqa: F811
    m = controller_module
    made = []
    monkeypatch.setattr(CaptureSession, "created", made)
    monkeypatch.setattr(m, "RealtimeSession", CaptureSession)
    monkeypatch.setattr(m.sys, "platform", "linux")
    m.config.REALTIME_ASR_SETTINGS = settings()
    m.config.ENABLE_TRANSCRIPTION_SEND = True
    m.config.ENABLE_CHECK_ENERGY_SEND = m.config.ENABLE_CHECK_ENERGY_RECEIVE = True
    m.config.VRC_MIC_MUTE_SYNC = False
    m.model.stopCaptureForRealtime.return_value = True
    c = m.Controller()
    c.run = MagicMock()
    c.messageFormatter = MagicMock(return_value="formatted")
    c.run_mapping.update(
        {
            key: "/run/" + key
            for key in (
                "word_filter",
                "error_translation_engine",
                "enable_translation",
                "error_translation_mic_vram_overflow",
                "error_translation_speaker_vram_overflow",
            )
        }
    )
    yield c, m, made
    for session in made:
        session.busy = False
    c._closeRealtimeASR()
    c.direct_voice.close()
    c.voice_route.close()
    c.voice_events.close()


def request(c, source="mic"):
    return dict(
        source=source,
        _realtime_generation=c.getRealtimeASRState()["result"][source]["generation"],
    )


def start(c, source="mic"):
    result = c.startRealtimeASR(request(c, source))
    assert result["status"] == 200, result


def captions(c):
    return [
        call.args[2]
        for call in c.run.call_args_list
        if call.args[1] == "/run/realtime_caption"
    ]


def test_settings_restore_choices_but_never_capture_and_validate_before_mutation(app):
    c, m, made = app
    assert c.getRealtimeASRSettings()["result"] == settings()
    assert all(
        not state["requested"] for state in c.getRealtimeASRState()["result"].values()
    )
    assert not made
    old = c.getRealtimeASRSettings()["result"]
    assert c.setRealtimeASRSettings({**old, "active": True})["status"] == 400
    assert c.getRealtimeASRSettings()["result"] == old
    changed = copy.deepcopy(old)
    changed["mic"]["language"] = "en"
    assert c.setRealtimeASRSettings(changed)["status"] == 200
    assert m.config.REALTIME_ASR_SETTINGS == changed
    other = m.Controller()
    try:
        assert other.getRealtimeASRSettings()["result"] == changed
        assert not made
    finally:
        other._closeRealtimeASR()
        other.direct_voice.close()
        other.voice_route.close()
        other.voice_events.close()


def test_sources_independent_and_legacy_capture_mutually_exclusive(app):
    c, m, made = app
    start(c)
    start(c, "speaker")
    assert all(session.active for session in made)
    assert m.model.stopCaptureForRealtime.call_args_list == [call("mic"), call("speaker")]
    c.startCheckMicEnergy()
    c.startCheckSpeakerEnergy()
    m.model.startCheckMicEnergy.assert_not_called()
    m.model.startCheckSpeakerEnergy.assert_not_called()
    assert (
        not m.config.ENABLE_TRANSCRIPTION_SEND
        and not m.config.ENABLE_TRANSCRIPTION_RECEIVE
    )
    assert c.startTranscriptionSendMessage()
    assert not made[0].active and made[1].active
    m.model.startMicTranscript.assert_called_once()


def test_settings_invalidate_affected_source_and_shared_changes_stop_both(app):
    c, m, made = app
    start(c)
    start(c, "speaker")
    old_request = request(c)
    changed = c.getRealtimeASRSettings()["result"]
    changed["mic"]["language"] = "en"
    c.setRealtimeASRSettings(changed)
    assert not made[0].active and made[1].active
    assert c.startRealtimeASR(old_request)["status"] == 409
    changed["model"] = "new"
    c.setRealtimeASRSettings(changed)
    assert not made[1].active


def test_fast_stop_invalidates_start_waiting_for_legacy_cleanup(app):
    c, m, made = app
    entered, release = Event(), Event()
    def handoff(source):
        entered.set()
        release.wait(2)
        return True
    m.model.stopCaptureForRealtime.side_effect = handoff
    result = []
    thread = Thread(target=lambda: result.append(c.startRealtimeASR(request(c))))
    thread.start()
    try:
        assert entered.wait(1)
        before = time.monotonic()
        assert c.stopRealtimeASR({"source": "mic"})["status"] == 200
        assert time.monotonic() - before < 0.1
        release.set()
        thread.join(2)
        assert result[0]["status"] == 409 and not made
    finally:
        release.set()
        thread.join(2)


def test_busy_previous_owner_blocks_restart_and_legacy_capture(app):
    c, m, made = app
    start(c)
    made[0].busy = True
    c.stopRealtimeASR({"source": "mic"})
    assert c.startRealtimeASR(request(c))["status"] == 409
    assert not c.startTranscriptionSendMessage()
    m.model.startMicTranscript.assert_not_called()
    assert len(made) == 1


def test_energy_control_does_not_claim_running_during_realtime(app):
    c, m, made = app
    start(c)
    start(c, "speaker")
    assert c.setEnableCheckMicThreshold()["result"] is False
    assert c.setEnableCheckSpeakerThreshold()["result"] is False
    assert any(
        call.args[1] == "/set/disable/check_mic_threshold"
        for call in c.run.call_args_list
    )
    assert any(
        call.args[1] == "/set/disable/check_speaker_threshold"
        for call in c.run.call_args_list
    )
    m.model.startCheckMicEnergy.assert_not_called()
    m.model.startCheckSpeakerEnergy.assert_not_called()


@pytest.mark.parametrize("source,cap", [("mic", "Mic"), ("speaker", "Speaker")])
def test_legacy_meter_can_resume_only_after_stopped_owner_drains(app, source, cap):
    c, m, made = app
    start(c, source)
    made[0].busy = True
    c.stopRealtimeASR({"source": source})
    assert getattr(c, "startCheck" + cap + "Energy")() is False
    made[0].busy = False
    assert getattr(c, "startCheck" + cap + "Energy")() is True
    getattr(m.model, "startCheck" + cap + "Energy").assert_called_once()


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_realtime_start_requires_confirmed_legacy_handoff(app, source):
    c, m, made = app
    m.model.stopCaptureForRealtime.return_value = False
    result = c.startRealtimeASR(request(c, source))
    assert result == {"status": 409, "result": {"error_code": "realtime_legacy_stop_failed"}}
    assert not made
    m.model.stopCaptureForRealtime.return_value = True
    start(c, source)
    assert len(made) == 1


def test_start_failure_invalidates_owner_and_allows_explicit_retry(app, monkeypatch):
    c, m, made = app
    original = CaptureSession.start

    def broken(session):
        original(session)
        raise RuntimeError("private OS exception")

    monkeypatch.setattr(CaptureSession, "start", broken)
    result = c.startRealtimeASR(request(c))
    assert result == {"status": 409, "result": {"error_code": "realtime_start_failed"}}
    assert not made[0].active
    monkeypatch.setattr(CaptureSession, "start", original)
    start(c)
    assert len(made) == 2 and made[1].active


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_partial_no_side_effects_and_final_once_with_speaker_never_rebroadcast(
    app, source
):
    c, m, made = app
    m.config.ENABLE_TRANSLATION = True
    m.config.SEND_RECEIVED_MESSAGE_TO_VRC = True
    m.model.getInputTranslate.return_value = (["hello"], [True])
    m.model.getOutputTranslate.return_value = (["hello"], [True])
    c.voice_events.publish = MagicMock()
    start(c, source)
    session = made[0]
    session.emit(revision=1)
    session.emit(revision=2)
    eventually(lambda: len(captions(c)) == 2)
    m.model.getInputTranslate.assert_not_called()
    m.model.getOutputTranslate.assert_not_called()
    m.model.oscSendMessage.assert_not_called()
    m.model.addTranslationHistory.assert_not_called()
    session.emit(final=True, revision=3)
    session.emit(final=True, revision=3)
    eventually(lambda: any(event["state"] == "translated" for event in captions(c)))
    translator = (
        m.model.getInputTranslate if source == "mic" else m.model.getOutputTranslate
    )
    translator.assert_called_once_with("text", source_language="Japanese")
    assert m.model.oscSendMessage.call_count == (1 if source == "mic" else 0)
    c.voice_events.publish.assert_not_called()
    m.model.addTranslationHistory.assert_called_once_with(source, "text")
    assert (
        m.model.websocketSendMessage.call_args.args[0]["type"]
        == "REALTIME_" + source.upper()
    )


@pytest.mark.parametrize("failure", ["success", "fallback", "vram"])
def test_stop_during_translation_discards_all_late_pipeline_effects(app, failure):
    c, m, made = app
    m.config.ENABLE_TRANSLATION = True
    entered, release = Event(), Event()

    def translate(*args, **kwargs):
        entered.set()
        release.wait(2)
        if failure == "vram":
            raise RuntimeError("private provider message")
        return ["translation"], [failure == "success"]

    m.model.getInputTranslate.side_effect = translate
    c.changeToCTranslate2Process = MagicMock()
    c.setDisableTranslation = MagicMock()
    start(c)
    try:
        made[0].emit(final=True)
        assert entered.wait(1)
        c.stopRealtimeASR({"source": "mic"})
        release.set()
        assert c._drainRealtimeASR("mic")
        m.model.oscSendMessage.assert_not_called()
        m.model.websocketSendMessage.assert_not_called()
        m.model.addTranslationHistory.assert_not_called()
        c.changeToCTranslate2Process.assert_not_called()
        c.setDisableTranslation.assert_not_called()
        assert not any(event["state"] == "translated" for event in captions(c))
    finally:
        release.set()


def test_shutdown_rejects_stale_and_fresh_start(app):
    c, m, made = app
    start(c)
    old = request(c)
    assert c._closeRealtimeASR()
    assert not made[0].active
    assert c.startRealtimeASR(old)["status"] == 409
    assert c.startRealtimeASR(request(c))["status"] == 409


def test_explicit_model_and_endpoint_lists_and_safe_errors(app, monkeypatch):
    from models.audio_routing.source_bridge import Endpoint
    from models.transcription.speechcpp_asr import RecognitionModel

    c, m, made = app
    service = MagicMock()
    service.recognizers.return_value = [RecognitionModel("asr", ("ja",), False)]
    monkeypatch.setattr(m, "SpeechCppASR", MagicMock(return_value=service))
    assert c.getRealtimeASRModels()["result"] == {
        "server": "external",
        "server_generation": None,
        "configured_url": "http://127.0.0.1:8080",
        "base_url": "http://127.0.0.1:8080",
        "models": [{"id": "asr", "languages": ("ja",), "accepts_language": False, "detects_language": False}],
        "error_code": None,
    }
    m.SpeechCppASR.assert_called_once_with("http://127.0.0.1:8080", timeout=5)
    monkeypatch.setattr(
        m,
        "enumerate_endpoints",
        lambda source: [
            {
                "endpoint": Endpoint(1, 2**63 + 1, "selected", "Audio/Source"),
                "label": "Microphone",
            }
        ],
    )
    row = c.getRealtimeASREndpoints({"source": "mic"})["result"]["endpoints"][0]
    assert row["endpoint"]["serial"] == str(2**63 + 1)
    service.recognizers.side_effect = RuntimeError("private response body")
    assert c.getRealtimeASRModels()["result"] == {
        "server": "external",
        "server_generation": None,
        "configured_url": "http://127.0.0.1:8080",
        "base_url": "http://127.0.0.1:8080",
        "models": [],
        "error_code": "realtime_models_unavailable",
    }
    monkeypatch.setattr(m.sys, "platform", "win32")
    assert (
        c.getRealtimeASREndpoints({"source": "mic"})["result"]["error_code"]
        == "realtime_linux_only"
    )
    assert (
        c.startRealtimeASR(request(c))["result"]["error_code"] == "realtime_linux_only"
    )
    assert not made


def test_real_config_persistence_contains_choices_not_capture_intent(tmp_path):
    import json
    from config import Config, ConfigValidationError

    cfg = object.__new__(Config)
    cfg.init_config()
    cfg._PATH_CONFIG = str(tmp_path / "config.json")
    try:
        assert cfg.REALTIME_ASR_SETTINGS == normalize_settings({})
        cfg.REALTIME_ASR_SETTINGS = settings()
        cfg.saveConfigToFile()
        persisted = json.loads((tmp_path / "config.json").read_text())
        assert persisted["REALTIME_ASR_SETTINGS"] == settings()
        with pytest.raises(ConfigValidationError):
            cfg.REALTIME_ASR_SETTINGS = {**settings(), "active": True}
        cfg.init_config()
        cfg._PATH_CONFIG = str(tmp_path / "config.json")
        cfg.load_config()
        assert cfg.REALTIME_ASR_SETTINGS == settings()
    finally:
        timer = getattr(cfg, "_timer", None)
        if timer:
            timer.cancel()


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"source": "mic"},
        {"source": "other", "_realtime_generation": 0},
        {"source": "mic", "_realtime_generation": True},
    ],
)
def test_invalid_start_never_captures(app, data):
    c, m, made = app
    assert c.startRealtimeASR(data)["status"] == 400
    assert not made


def test_stop_receiver_bypasses_queue_and_overwrites_frontend_generation(
    mainloop_module,  # noqa: F811
    monkeypatch,
):
    mod, pending, responses = mainloop_module, Queue(), Queue()
    c = mod.controller
    old = request(c)
    main = mod.Main(c, mod.main_instance.mapping)
    monkeypatch.setattr(
        mod.sys, "stdin", type("Input", (), {"readline": lambda self: pending.get()})()
    )
    monkeypatch.setattr(mod, "printResponse", lambda s, e, r: responses.put((s, e, r)))
    main.startReceiver()
    try:
        pending.put(
            wire_message(
                "/run/start_realtime_asr", {**old, "_realtime_generation": 999}
            )
        )
        pending.put(wire_message("/run/stop_realtime_asr", {"source": "mic"}))
        status, endpoint, result = responses.get(timeout=1)
        assert status == 200 and endpoint == "/run/stop_realtime_asr"
        queued_endpoint, data, _ = main.queue.get(timeout=1)
        assert data["_realtime_generation"] == old["_realtime_generation"]
        result, status = main._call_handler(queued_endpoint, data)
        assert status == 409 and result["error_code"] == "realtime_stale_start"
    finally:
        main._stop_event.set()
        pending.put("")
        for thread in main._threads:
            thread.join(2)
        c._closeRealtimeASR()
