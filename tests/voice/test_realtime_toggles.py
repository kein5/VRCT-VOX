"""Linux Mic/Speaker main toggles drive realtime ASR; Windows keeps the legacy recorder.

Real Controller with the fakes of test_realtime_controls: capture, the ASR
client and the speech server are injected, nothing is recorded or loaded.
"""

import copy
from unittest.mock import MagicMock

import pytest

from models.audio_routing.source_bridge import Endpoint
from models.transcription.realtime_events import TranscriptUpdate
from models.transcription.speechcpp_asr import RecognitionModel
from test_controller_integration import controller_module  # noqa: F401
from test_realtime_controls import CaptureSession, app, captions, request  # noqa: F401
from test_realtime_delivery import eventually

QWEN = RecognitionModel("Qwen3-ASR-0.6B", ("de", "en", "ja"), True, True)
HAAS = RecognitionModel("Haas-616M-ja-v1.0", ("ja",), True, False)


def recognizers(m, monkeypatch, *models):
    service = MagicMock()
    service.recognizers.return_value = list(models)
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(m, "SpeechCppASR", factory)
    return factory


def pushed(c, endpoint):
    return [call.args for call in c.run.call_args_list if call.args[1] == endpoint]


def configure(c, **changes):
    value = c.getRealtimeASRSettings()["result"]
    for key, row in changes.items():
        if isinstance(row, dict):
            value[key].update(row)
        else:
            value[key] = row
    assert c.setRealtimeASRSettings(value)["status"] == 200


class FakeServers:
    """SpeechServers' public surface for the asr profile, without a process."""

    def __init__(self, state="stopped", fail=None):
        self.row = dict(state=state, base_url="http://127.0.0.1:9911" if state == "ready" else None,
                        error_code=None, generation=0)
        self.fail, self.started, self.stopped = fail, [], []

    def state(self):
        return {"asr": copy.deepcopy(self.row)}

    def start(self, profile, options, generation):
        assert profile == "asr" and generation == self.row["generation"]
        self.started.append(options)
        self.row["generation"] += 1
        if self.fail:
            self.row.update(state="failed", error_code=self.fail, generation=self.row["generation"] + 1)
        else:
            self.row.update(state="ready", base_url="http://127.0.0.1:9911")

    def binding(self, profile):
        if self.row["state"] != "ready":
            raise RuntimeError("speech_server_not_ready")
        return self.row["base_url"]

    def stop(self, profile, generation=None):
        if generation is not None and generation != self.row["generation"]:
            return False
        self.stopped.append(generation)
        self.row.update(state="stopped", base_url=None, generation=self.row["generation"] + 1)
        return True


def gguf(path):
    path.write_bytes(b"GGUF" + bytes(16))
    return str(path)


@pytest.mark.parametrize("source,direction", [("mic", "Send"), ("speaker", "Receive")])
def test_linux_toggle_starts_and_stops_realtime_not_the_legacy_recorder(app, monkeypatch, source, direction):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN, RecognitionModel("asr", ("ja",), True))
    m.config.ENABLE_TRANSCRIPTION_SEND = m.config.ENABLE_TRANSCRIPTION_RECEIVE = False
    endpoint = "/set/%s/transcription_" + direction.lower()
    assert getattr(c, "setEnableTranscription" + direction)() == {"status": 200, "result": True}
    assert len(made) == 1 and made[0].source == source and made[0].active
    assert made[0].options.model == "asr" and made[0].options.language == "ja"
    getattr(m.model, "start" + ("Mic" if source == "mic" else "Speaker") + "Transcript").assert_not_called()
    # The legacy flag stays off: device-change paths keyed on it stay inert.
    assert getattr(m.config, "ENABLE_TRANSCRIPTION_" + direction.upper()) is False
    assert pushed(c, endpoint % "enable") == [(200, endpoint % "enable", True)]
    assert not pushed(c, endpoint % "disable")
    assert c.getRealtimeASRState()["result"][source]["requested"]
    # ON again is idempotent: the Config page restores toggles this way.
    assert getattr(c, "setEnableTranscription" + direction)()["result"] is True and len(made) == 1
    assert getattr(c, "setDisableTranscription" + direction)() == {"status": 200, "result": False}
    assert not made[0].active
    assert pushed(c, endpoint % "disable") == [(200, endpoint % "disable", False)]


def test_config_page_start_and_stop_show_on_the_toggle_without_turning_it_off(app):
    c, m, made = app
    assert c.startRealtimeASR(request(c, "speaker"))["status"] == 200
    # Starting realtime used to push the legacy toggle OFF; on Linux it is the toggle.
    assert not pushed(c, "/set/disable/transcription_receive")
    assert pushed(c, "/set/enable/transcription_receive") == [(200, "/set/enable/transcription_receive", True)]
    c.stopRealtimeASR({"source": "speaker"})
    assert pushed(c, "/set/disable/transcription_receive") == [(200, "/set/disable/transcription_receive", False)]


def test_settings_change_stops_the_session_and_its_toggle(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, RecognitionModel("asr", ("en", "ja"), True))
    assert c.setEnableTranscriptionSend()["result"] is True
    configure(c, mic={"language": "en"})
    assert not made[0].active
    assert pushed(c, "/set/disable/transcription_send")[-1] == (200, "/set/disable/transcription_send", False)


def test_spontaneous_failure_turns_the_toggle_off_with_its_reason(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, RecognitionModel("asr", ("ja",), True))
    assert c.setEnableTranscriptionReceive()["result"] is True
    session = made[0]
    session.health = lambda: dict(source="speaker", namespace=session.namespace, state="failed",
                                  error_code="realtime_capture_failed")
    session.active = False
    eventually(lambda: pushed(c, "/set/enable/transcription_receive")[-1][0] == 400)
    status, _, result = pushed(c, "/set/enable/transcription_receive")[-1]
    assert result["error_code"] == "TRANSCRIPTION_RECEIVE_NOT_READY" and result["data"] is False
    assert result["details"] == {"reason": "realtime_capture_failed"}
    # A later ON starts a fresh session instead of reporting "already started".
    assert c.setEnableTranscriptionReceive()["result"] is True and len(made) == 2


@pytest.mark.parametrize("change,models,reason", [
    (dict(mic={"endpoint": None, "follow_default": False}), (QWEN,), "realtime_endpoint_required"),
    (dict(model=""), (), "realtime_model_required"),
    (dict(model="gone"), (QWEN,), "realtime_model_unavailable"),
    (dict(model="Haas-616M-ja-v1.0", mic={"language": "auto"}), (HAAS,), "realtime_language_auto_unsupported"),
    (dict(model="Haas-616M-ja-v1.0", mic={"language": "en"}), (HAAS,), "realtime_language_unsupported"),
])
def test_not_configured_toggle_returns_not_ready_and_starts_nothing(app, monkeypatch, change, models, reason):
    c, m, made = app
    recognizers(m, monkeypatch, *models)
    configure(c, **change)
    c.run.reset_mock()
    result = c.setEnableTranscriptionSend()
    assert result["status"] == 400
    assert result["result"]["error_code"] == "TRANSCRIPTION_SEND_NOT_READY"
    assert result["result"]["details"] == {"reason": reason} and result["result"]["data"] is False
    assert not made and not pushed(c, "/set/enable/transcription_send")
    m.model.startMicTranscript.assert_not_called()


def test_unreachable_external_server_is_not_ready(app, monkeypatch):
    c, m, made = app
    service = MagicMock()
    service.recognizers.side_effect = RuntimeError("private body")
    monkeypatch.setattr(m, "SpeechCppASR", MagicMock(return_value=service))
    result = c.setEnableTranscriptionReceive()["result"]
    assert result["error_code"] == "TRANSCRIPTION_RECEIVE_NOT_READY"
    assert result["details"] == {"reason": "realtime_models_unavailable"} and not made


def test_speaker_auto_translates_from_each_detected_language(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN)
    configure(c, model="Qwen3-ASR-0.6B", speaker={"language": "auto"})
    m.config.ENABLE_TRANSLATION = True
    m.model.getOutputTranslate.return_value = (["hallo"], [True])
    assert c.setEnableTranscriptionReceive()["result"] is True
    session = made[0]
    assert session.options.language == "auto"
    for item, code in (("a", "de"), ("b", ""), ("c", "xx")):
        session.updates.put(TranscriptUpdate("speaker", session.namespace, item, 1, "text " + item, True, "final",
                                             received_ns=int(session.clock() * 1e9), language=code))
    eventually(lambda: m.model.getOutputTranslate.call_count == 3)
    sources = [call.kwargs["source_language"] for call in m.model.getOutputTranslate.call_args_list]
    # German as detected; no or an untranslatable code falls back to the
    # speaker's VRCT language, as the legacy recorder does.
    fallback = m.config.SELECTED_TARGET_LANGUAGES[m.config.SELECTED_TAB_NO]["1"]["language"]
    assert sources == ["German", fallback, fallback]


def test_mic_ja_and_speaker_auto_run_side_by_side_on_one_model(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN)
    configure(c, model="Qwen3-ASR-0.6B", mic={"language": "ja"}, speaker={"language": "auto"})
    assert c.setEnableTranscriptionSend()["result"] is True
    assert c.setEnableTranscriptionReceive()["result"] is True
    assert [(s.source, s.options.model, s.options.language) for s in made] == [
        ("mic", "Qwen3-ASR-0.6B", "ja"), ("speaker", "Qwen3-ASR-0.6B", "auto")]


def test_follow_default_resolves_once_and_pins_that_endpoint(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, RecognitionModel("asr", ("ja",), True))
    configure(c, speaker={"endpoint": None, "follow_default": True})
    sink = Endpoint(7, 42, "alsa_output.headphones", "Audio/Sink")
    resolve = MagicMock(return_value=sink)
    monkeypatch.setattr(m, "default_endpoint", resolve)
    assert c.setEnableTranscriptionReceive()["result"] is True
    assert made[0].endpoint == sink
    resolve.assert_called_with("speaker")
    c.setDisableTranscriptionReceive()
    resolve.side_effect = ValueError("realtime_default_endpoint_feedback")
    result = c.setEnableTranscriptionReceive()["result"]
    assert result["details"] == {"reason": "realtime_default_endpoint_feedback"} and len(made) == 1


def test_bundled_toggle_starts_its_server_and_stops_only_that_run(app, monkeypatch, tmp_path):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN)
    configure(c, server="bundled", model="")  # The bundled server's one recognizer is used.
    c.speech_servers = servers = FakeServers()
    c._speech_settings["profiles"]["asr"].update(model=gguf(tmp_path / "asr.gguf"), vad_model=gguf(tmp_path / "vad.gguf"))
    assert c.setEnableTranscriptionSend()["result"] is True
    assert len(servers.started) == 1 and servers.started[0]["vad_model"].endswith("vad.gguf")
    assert made[0].options.base_url == "http://127.0.0.1:9911" and made[0].options.model == "Qwen3-ASR-0.6B"
    assert c.setEnableTranscriptionReceive()["result"] is True
    assert len(servers.started) == 1  # Both toggles share the one server.
    c.setDisableTranscriptionSend()
    assert not servers.stopped  # Speaker still uses it.
    c.setDisableTranscriptionReceive()
    assert servers.stopped == [1] and servers.row["state"] == "stopped"


def test_bundled_server_started_from_settings_keeps_running(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN)
    configure(c, server="bundled", model="Qwen3-ASR-0.6B")
    c.speech_servers = servers = FakeServers("ready")
    assert c.setEnableTranscriptionSend()["result"] is True
    c.setDisableTranscriptionSend()
    assert not servers.started and not servers.stopped and servers.row["state"] == "ready"


@pytest.mark.parametrize("profile,fail,reason", [
    (dict(model="", vad_model=""), None, "realtime_asr_model_missing"),
    (dict(vad_model=""), None, "realtime_vad_model_missing"),
    (dict(vad_model="/missing/vad.gguf"), None, "speech_server_model_invalid"),
    ({}, "speech_server_out_of_memory", "speech_server_out_of_memory"),
    ({}, "speech_server_exited", "speech_server_start_failed"),
])
def test_bundled_server_that_cannot_start_is_not_ready(app, monkeypatch, tmp_path, profile, fail, reason):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN)
    configure(c, server="bundled")
    c.speech_servers = servers = FakeServers(fail=fail)
    row = dict(model=gguf(tmp_path / "asr.gguf"), vad_model=gguf(tmp_path / "vad.gguf"))
    row.update(profile)
    c._speech_settings["profiles"]["asr"].update(row)
    result = c.setEnableTranscriptionReceive()["result"]
    assert result["error_code"] == "TRANSCRIPTION_RECEIVE_NOT_READY"
    assert result["details"] == {"reason": reason} and not made
    assert bool(servers.started) == (fail is not None)


def test_asr_server_crash_turns_bundled_toggles_off_with_the_server_code(app, monkeypatch, tmp_path):
    c, m, made = app
    recognizers(m, monkeypatch, QWEN)
    configure(c, server="bundled", model="Qwen3-ASR-0.6B")
    c.speech_servers = servers = FakeServers("ready")
    assert c.setEnableTranscriptionSend()["result"] is True
    servers.row.update(state="failed", error_code="speech_server_exited", base_url=None)
    c._speechServerEnded("asr")
    status, _, result = pushed(c, "/set/enable/transcription_send")[-1]
    assert status == 400 and result["details"] == {"reason": "speech_server_exited"}
    assert not made[0].active


@pytest.mark.parametrize("source,direction,cap", [("mic", "Send", "Mic"), ("speaker", "Receive", "Speaker")])
def test_windows_toggles_keep_the_legacy_recorder(app, monkeypatch, source, direction, cap):
    c, m, made = app
    monkeypatch.setattr(m.sys, "platform", "win32")
    factory = recognizers(m, monkeypatch, QWEN)
    setattr(m.config, "ENABLE_TRANSCRIPTION_" + direction.upper(), False)
    getattr(m.model, "start" + cap + "Transcript").return_value = True
    assert getattr(c, "setEnableTranscription" + direction)() == {"status": 200, "result": True}
    getattr(m.model, "start" + cap + "Transcript").assert_called_once()
    assert getattr(m.config, "ENABLE_TRANSCRIPTION_" + direction.upper()) is True
    assert not made and not factory.called
    assert getattr(c, "setDisableTranscription" + direction)() == {"status": 200, "result": False}
    getattr(m.model, "stop" + cap + "Transcript").assert_called_once()
    assert not [call for call in c.run.call_args_list if "transcription_" in call.args[1]]


def test_captions_still_flow_after_a_toggle_start(app, monkeypatch):
    c, m, made = app
    recognizers(m, monkeypatch, RecognitionModel("asr", ("ja",), True))
    assert c.setEnableTranscriptionSend()["result"] is True
    made[0].emit(revision=1)
    eventually(lambda: len(captions(c)) == 1)
