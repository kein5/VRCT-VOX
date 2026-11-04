"""Consent and fail-closed ASR startup using fake devices/providers only."""
import ast
import json
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from typing import Optional
from unittest.mock import Mock

import pytest

from errors import ErrorCode, TranscriptionStartError, VRCTError
from models.transcription import transcription_transcriber as transcriber_module
from test_config_persistence_regressions import definitions, isolated  # noqa: F401


@pytest.fixture(autouse=True)
def engine_catalog(isolated):
    isolated.config._SELECTABLE_TRANSCRIPTION_ENGINE_LIST = [
        "Google", "Whisper", "Groq_Whisper", "OpenAI_Whisper", "Custom_Whisper", "Deepgram"]


@pytest.mark.parametrize("saved", [{}, {"SELECTED_TRANSCRIPTION_ENGINE": None},
                                   {"SELECTED_TRANSCRIPTION_ENGINE": "Google"},
                                   {"SELECTED_TRANSCRIPTION_ENGINE": "Whisper"}])
def test_config_selection_round_trip(isolated, saved):
    config = isolated.config
    isolated.path.write_text(json.dumps(saved))
    config.load_config()
    assert config.SELECTED_TRANSCRIPTION_ENGINE == saved.get("SELECTED_TRANSCRIPTION_ENGINE")
    config.saveConfigToFile()
    assert json.loads(isolated.path.read_text())["SELECTED_TRANSCRIPTION_ENGINE"] == saved.get("SELECTED_TRANSCRIPTION_ENGINE")


def test_invalid_engine_is_rejected_without_selecting_google(isolated):
    config = isolated.config
    for value in ("", "unselected", "unknown", 1, False, {}):
        with pytest.raises(isolated.ns["ConfigValidationError"]):
            config.SELECTED_TRANSCRIPTION_ENGINE = value
        assert config.SELECTED_TRANSCRIPTION_ENGINE is None


def make_controller(config, backend):
    namespace = dict(config=config, model=backend, ErrorCode=ErrorCode, VRCTError=VRCTError,
                     TranscriptionStartError=TranscriptionStartError, Optional=Optional)
    definitions("controller.py", namespace, class_methods={
        "setEnableTranscriptionSend", "setEnableTranscriptionReceive",
        "_startTranscriptionSendMessageLocked", "_startTranscriptionReceiveMessageLocked",
        "updateTranscriptionEngine",
    })
    controller = namespace["Controller"]()
    controller._realtimeToggles = lambda: False
    controller._audioLock = lambda _: RLock()
    controller._audioGeneration = Mock()
    controller._wireAudioSessionLocked = Mock()
    controller.stopRealtimeASR = Mock()
    controller._drainRealtimeASR = lambda _: True
    controller.micMessage = controller.speakerMessage = Mock()
    controller.run = Mock()
    controller.fallbackUnsupportedLanguagesForTranscriptionEngine = Mock()
    controller.run_mapping = {"selectable_language_list": "/run/selectable_language_list"}
    return controller


@pytest.mark.parametrize("direction", ["Send", "Receive"])
def test_fresh_config_enable_returns_not_selected_without_capture(isolated, direction):
    backend = Mock()
    controller = make_controller(isolated.config, backend)
    response = getattr(controller, "setEnableTranscription" + direction)()
    assert response["status"] == 400
    assert response["result"]["error_code"] == "TRANSCRIPTION_ENGINE_NOT_SELECTED"
    assert response["result"]["data"] is False
    assert backend.mock_calls == []
    assert controller._wireAudioSessionLocked.mock_calls == []
    assert not isolated.config.ENABLE_TRANSCRIPTION_SEND
    assert not isolated.config.ENABLE_TRANSCRIPTION_RECEIVE


@pytest.mark.parametrize("engine", [None, "Google", "Whisper", "Groq_Whisper", "OpenAI_Whisper", "Custom_Whisper", "Deepgram"])
def test_unavailable_engine_selection_is_kept(isolated, engine):
    isolated.config.SELECTED_TRANSCRIPTION_ENGINE = engine
    isolated.config.SELECTABLE_TRANSCRIPTION_ENGINE_STATUS = {}
    controller = make_controller(isolated.config, Mock())
    controller.updateTranscriptionEngine()
    assert isolated.config.SELECTED_TRANSCRIPTION_ENGINE == engine
    controller.run.assert_not_called()


def fake_session(engine):
    # Execute the production startup method without importing/initializing the app.
    path = Path(__file__).resolve().parents[1] / "model.py"
    tree = ast.parse(path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_AudioDeviceSession")
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_start"]
    namespace = dict(Optional=Optional, TranscriptionStartError=TranscriptionStartError, ErrorCode=ErrorCode)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    session = namespace["_AudioDeviceSession"]()
    session.features = {"transcript"}
    session._pipeline_error_lock = RLock()
    session._create_transcriber = lambda: transcriber_module.AudioTranscriber(
        False, None, 3, 10, engine, root="unused", whisper_weight_type="base")
    session._create_recorder = Mock(side_effect=AssertionError("capture must not open"))
    session.terminal_failure_fnc = Mock()
    session._stop = Mock()
    return session


@pytest.mark.parametrize("direction,source", [("Send", "mic"), ("Receive", "speaker")])
@pytest.mark.parametrize("engine,check,error", [
    ("Whisper", False, ErrorCode.TRANSCRIPTION_MODEL_MISSING),
    ("Whisper", True, ErrorCode.TRANSCRIPTION_MODEL_MISSING),
    ("Whisper", OSError("verification failed"), ErrorCode.TRANSCRIPTION_MODEL_MISSING),
    ("Groq_Whisper", True, ErrorCode.TRANSCRIPTION_ENGINE_UNAVAILABLE),
    ("OpenAI_Whisper", True, ErrorCode.TRANSCRIPTION_ENGINE_UNAVAILABLE),
    ("Custom_Whisper", True, ErrorCode.TRANSCRIPTION_ENGINE_UNAVAILABLE),
    ("Deepgram", True, ErrorCode.TRANSCRIPTION_ENGINE_UNAVAILABLE),
])
def test_failed_selected_engine_reports_error_before_capture(isolated, monkeypatch, direction, source, engine, check, error):
    google = Mock(side_effect=AssertionError("Google was not selected"))
    monkeypatch.setattr(transcriber_module, "GoogleProvider", google)
    monkeypatch.setattr(transcriber_module, "checkWhisperWeight",
                        Mock(side_effect=check) if isinstance(check, Exception) else Mock(return_value=check))
    model_loader = Mock(side_effect=FileNotFoundError("loader verification failed")
                        if engine == "Whisper" and check is True else AssertionError("unverified weights must not load"))
    monkeypatch.setattr(transcriber_module, "getWhisperModel", model_loader)
    for name in ("OpenAICompatibleTranscriptionProvider", "DeepgramProvider"):
        monkeypatch.setattr(transcriber_module, name, Mock(side_effect=ValueError("invalid provider")))
    isolated.config.SELECTED_TRANSCRIPTION_ENGINE = engine
    session = fake_session(engine)
    backend = Mock()
    getattr(backend, "startMicTranscript" if source == "mic" else "startSpeakerTranscript").side_effect = (
        lambda _: session._start(device={"name": "fake"}))
    controller = make_controller(isolated.config, backend)
    response = getattr(controller, "setEnableTranscription" + direction)()
    assert response == {"status": 200, "result": False}
    status, endpoint, result = controller.run.call_args.args
    assert status == 400
    assert endpoint == "/set/enable/transcription_" + ("send" if source == "mic" else "receive")
    assert result["error_code"] == error.value
    assert result["data"] is False
    assert isolated.config.SELECTED_TRANSCRIPTION_ENGINE == engine
    session._create_recorder.assert_not_called()
    session._stop.assert_called_once()
    google.assert_not_called()
    if engine == "Whisper" and check is True:
        model_loader.assert_called_once()
    else:
        model_loader.assert_not_called()


@pytest.mark.parametrize("engine", [None, "unknown", ""])
def test_transcriber_has_no_implicit_provider(monkeypatch, engine):
    google = Mock()
    monkeypatch.setattr(transcriber_module, "GoogleProvider", google)
    with pytest.raises(TranscriptionStartError):
        transcriber_module.AudioTranscriber(False, None, 3, 10, engine)
    google.assert_not_called()


def test_explicit_google_is_the_only_google_provider_route(monkeypatch):
    google = Mock()
    monkeypatch.setattr(transcriber_module, "GoogleProvider", google)
    transcriber = transcriber_module.AudioTranscriber(False, None, 3, 10, "Google")
    assert transcriber._resolve_provider() is google.return_value
    transcriber.transcription_engine = None
    with pytest.raises(TranscriptionStartError):
        transcriber._resolve_provider()
    google.assert_called_once()


@pytest.mark.parametrize("direction,source", [("Send", "mic"), ("Receive", "speaker")])
def test_linux_realtime_toggle_remains_independent_of_legacy_selection(isolated, direction, source):
    controller = make_controller(isolated.config, Mock())
    controller._realtimeToggles = lambda: True
    controller._enableRealtimeToggle = Mock(return_value={"status": 200, "result": True})
    assert getattr(controller, "setEnableTranscription" + direction)()["result"] is True
    controller._enableRealtimeToggle.assert_called_once_with(source, None)
