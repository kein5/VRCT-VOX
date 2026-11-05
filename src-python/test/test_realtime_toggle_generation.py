"""Receipt-to-start cancellation with memory-only servers, sessions and capture."""

import base64
import importlib.util
import io
import json
from pathlib import Path
from threading import Event, Lock, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import controller as module
from models.transcription.speechcpp_asr import RecognitionModel


class FakeServers:
    def __init__(self):
        self.row = dict(state="stopped", generation=0, error_code=None)
        self.started = []
        self.stopped = []

    def state(self):
        return {"asr": dict(self.row)}

    def start(self, profile, options, generation):
        assert profile == "asr" and generation == self.row["generation"]
        self.row.update(state="ready", generation=generation + 1)
        self.started.append(generation + 1)

    def binding(self, profile):
        assert profile == "asr" and self.row["state"] == "ready"
        return "http://127.0.0.1:9911"

    def stop(self, profile, generation=None):
        assert profile == "asr"
        if generation != self.row["generation"]:
            return False
        self.stopped.append(generation)
        self.row.update(state="stopped", generation=generation + 1)
        return True


class FakeSession:
    def __init__(self, source, options, endpoint, *, snapshot_voice=None):
        self.source = source
        self.active = False
        self.released = False
        self.capture = SimpleNamespace(active=False, released=False)

    def health(self):
        return dict(source=self.source, namespace=None, error_code=None,
                    state="closed" if self.released else "ready" if self.active else "idle")

    def start(self):
        assert not self.released
        self.active = self.capture.active = True

    def request_stop(self):
        self.active = self.capture.active = False
        self.released = self.capture.released = True

    def close(self, timeout=3):
        self.request_stop()
        return True


class FakeDelivery:
    def __init__(self, session, *args, **kwargs):
        self.session = session
        self.released = False

    def start(self):
        pass

    def request_stop(self):
        self.session.request_stop()
        self.released = True

    def close(self, timeout=3):
        self.request_stop()
        return True


@pytest.fixture
def app(monkeypatch):
    # Bypass Controller construction: no app workers, models or services start.
    c = module.Controller.__new__(module.Controller)
    settings = {"server": "bundled", "model": "asr"}
    for source, media in (("mic", "Audio/Source"), ("speaker", "Audio/Sink")):
        settings[source] = dict(language="ja", endpoint=dict(
            cookie="1", serial="2", name=source, media_class=media))
        setattr(c, source + "_lifecycle_lock", Lock())
    c._initRealtimeASR(settings)
    c._speech_settings_lock = Lock()
    c._speech_settings = {"profiles": {"asr": {"model": "fake", "vad_model": "fake"}}}
    c.speech_servers = FakeServers()
    c.voice_events = MagicMock()
    c.run = MagicMock()
    made = []

    def session(*args, **kwargs):
        result = FakeSession(*args, **kwargs)
        made.append(result)
        return result

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "config", SimpleNamespace(
        SELECTED_TRANSCRIPTION_ENGINE="Google",
        ENABLE_TRANSCRIPTION_SEND=False, ENABLE_TRANSCRIPTION_RECEIVE=False))
    monkeypatch.setattr(module, "model", MagicMock())
    module.model.stopCaptureForRealtime.return_value = True
    monkeypatch.setattr(module, "RealtimeSession", session)
    monkeypatch.setattr(module, "RealtimeDelivery", FakeDelivery)
    monkeypatch.setattr(module, "speech_start_options", lambda *args: {})
    service = MagicMock()
    service.recognizers.return_value = [RecognitionModel("asr", ("ja",), True)]
    monkeypatch.setattr(module, "SpeechCppASR", MagicMock(return_value=service))
    yield SimpleNamespace(c=c, made=made, service=service)
    c._closeRealtimeASR()
    c._releaseAsrServer()


@pytest.fixture
def dispatch(app, monkeypatch, tmp_path):
    # Load the actual receiver/mapping, substituting the already isolated
    # controller and crash log. Main.start()/Controller.init() are never called.
    import faulthandler
    import utils

    monkeypatch.setattr(module, "Controller", lambda: app.c)
    monkeypatch.setattr(faulthandler, "enable", lambda **kwargs: None)
    monkeypatch.setattr(utils, "openTraceLog", lambda name: (str(tmp_path / name), io.StringIO()))
    spec = importlib.util.spec_from_file_location(
        "generation_test_mainloop", Path(module.__file__).with_name("mainloop.py"))
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    app.c.run = MagicMock()
    main = loop.main_instance
    for handler in main.mapping.values():
        handler["status"] = True
    responses = []
    monkeypatch.setattr(loop, "printLog", lambda *args: None)
    monkeypatch.setattr(loop, "errorLogging", lambda: pytest.fail("receiver raised"))
    monkeypatch.setattr(loop, "printResponse", lambda *args: responses.append(args))

    def receive(*requests):
        lines = iter(json.dumps({"endpoint": endpoint, "data": None if data is None else
                     base64.b64encode(json.dumps(data).encode()).decode()}) + "\n"
                     for endpoint, data in requests)

        def readline():
            line = next(lines, None)
            if line is None:
                main._stop_event.set()
                return ""
            return line

        monkeypatch.setattr(loop.sys, "stdin", SimpleNamespace(readline=readline))
        main._stop_event.clear()
        main.receiver()

    yield SimpleNamespace(main=main, receive=receive, responses=responses)
    loop._cleanupCrashTraceIfEmpty()


def enable_endpoint(source):
    return "/set/enable/transcription_" + ("send" if source == "mic" else "receive")


def queued_enable(dispatch, source, data=None):
    dispatch.receive((enable_endpoint(source), data))
    endpoint, data, attempt = dispatch.main.queue.get_nowait()
    assert attempt == 0
    return endpoint, data


def stop(dispatch, source):
    dispatch.receive(("/run/stop_realtime_asr", {"source": source}))
    status, endpoint, result = dispatch.responses[-1]
    assert (status, endpoint) == (200, "/run/stop_realtime_asr")
    assert result[source]["requested"] is False


def assert_stale(response, source):
    result, status = response
    direction = "SEND" if source == "mic" else "RECEIVE"
    assert status == 400
    assert result["error_code"] == "TRANSCRIPTION_" + direction + "_NOT_READY"
    assert result["data"] is False
    assert result["details"] == {"reason": "realtime_stale_start"}


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("payload", [None, True, {"_realtime_generation": 999}])
def test_queued_enable_is_stamped_before_fast_stop(app, dispatch, source, payload):
    request = queued_enable(dispatch, source, payload)
    assert request[1]["_realtime_generation"] == 0
    stop(dispatch, source)
    assert_stale(dispatch.main._call_handler(*request), source)
    assert not app.made and not app.c.speech_servers.started
    app.service.recognizers.assert_not_called()


@pytest.mark.parametrize("source,direction", [("mic", "Send"), ("speaker", "Receive")])
def test_direct_enable_snapshot_precedes_preparation(app, monkeypatch, source, direction):
    original = app.c._prepareRealtimeToggle

    def prepare(*args):
        result = original(*args)
        app.c.stopRealtimeASR({"source": source})
        return result

    monkeypatch.setattr(app.c, "_prepareRealtimeToggle", prepare)
    response = getattr(app.c, "setEnableTranscription" + direction)()
    assert_stale((response["result"], response["status"]), source)
    assert not app.made
    assert app.c.speech_servers.stopped == [1]


@pytest.mark.parametrize("source,direction", [("mic", "Send"), ("speaker", "Receive")])
def test_preparation_exception_releases_owned_server(app, monkeypatch, source, direction):
    original = app.c._prepareRealtimeToggle

    def prepare(*args):
        original(*args)
        app.c.stopRealtimeASR({"source": source})
        raise RuntimeError("preparation failed after stop")

    monkeypatch.setattr(app.c, "_prepareRealtimeToggle", prepare)
    with pytest.raises(RuntimeError, match="preparation failed after stop"):
        getattr(app.c, "setEnableTranscription" + direction)()
    assert not app.made
    assert app.c._asr_toggle_starting == 0 and app.c._asr_server_owned is None
    assert app.c.speech_servers.stopped == [1]


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("phase", ["server_wait", "models", "prepared", "handoff", "started"])
def test_stop_during_enable_releases_attempt_resources(app, dispatch, monkeypatch, source, phase):
    c = app.c
    entered, release = Event(), Event()

    def pause():
        entered.set()
        assert release.wait(3), "test did not release preparation"

    if phase == "server_wait":
        original = c.speech_servers.start

        def start_server(*args):
            original(*args)
            c.speech_servers.row["state"] = "preparing"
            pause()

        monkeypatch.setattr(c.speech_servers, "start", start_server)
    elif phase == "models":
        def models():
            pause()
            return [RecognitionModel("asr", ("ja",), True)]

        app.service.recognizers.side_effect = models
    elif phase in ("prepared", "started"):
        name = "_prepareRealtimeToggle" if phase == "prepared" else "_startRealtime"
        original = getattr(c, name)

        def prepared(*args):
            result = original(*args)
            pause()
            return result

        monkeypatch.setattr(c, name, prepared)
    else:
        def handoff(*args):
            pause()
            return True

        module.model.stopCaptureForRealtime.side_effect = handoff

    request = queued_enable(dispatch, source)
    responses = []
    worker = Thread(target=lambda: responses.append(dispatch.main._call_handler(*request)), daemon=True)
    worker.start()
    try:
        assert entered.wait(2)
        # Server start holds the toggle lock briefly; stop must still advance
        # the generation before that nonblocking start call finishes.
        if phase == "server_wait":
            release.set()
        stop(dispatch, source)
        if phase != "server_wait":
            assert worker.is_alive(), "stop must finish while preparation is blocked"
        assert c.getRealtimeASRState()["result"][source]["requested"] is False
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    if phase == "started":
        assert responses[0][1] == 400  # Existing failed/inactive toggle response.
        assert len(app.made) == 1
        session, delivery = c._realtime_owners[source]
        assert session.released and session.capture.released and delivery.released
        assert not session.capture.active
    else:
        assert_stale(responses[0], source)
        assert not app.made
        assert c._realtime_owners[source] is None
    assert c._asr_toggle_starting == 0 and c._asr_server_owned is None
    assert c.speech_servers.stopped == c.speech_servers.started == [1]
    assert c.speech_servers.row["state"] == "stopped"
    assert not c._realtime_requested[source]


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("prior_stop", [False, True])
def test_current_enable_starts_and_remains_idempotent(app, dispatch, source, prior_stop):
    if prior_stop:
        stop(dispatch, source)
    assert dispatch.main._call_handler(*queued_enable(dispatch, source)) == (True, 200)
    assert app.c.getRealtimeASRState()["result"][source]["requested"] is True
    assert len(app.made) == 1 and app.made[0].capture.active
    assert dispatch.main._call_handler(*queued_enable(dispatch, source)) == (True, 200)
    assert len(app.made) == 1


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("last", ["enable", "stop"])
def test_repeated_stops_and_enables_end_in_last_requested_state(app, dispatch, source, last):
    for _ in range(4):
        old = queued_enable(dispatch, source)
        stop(dispatch, source)
        new = queued_enable(dispatch, source)
        assert_stale(dispatch.main._call_handler(*old), source)
        assert dispatch.main._call_handler(*new) == (True, 200)
        stop(dispatch, source)
        assert all(session.capture.released for session in app.made)
    if last == "enable":
        assert dispatch.main._call_handler(*queued_enable(dispatch, source)) == (True, 200)
    assert app.c.getRealtimeASRState()["result"][source]["requested"] is (last == "enable")
    assert sum(session.capture.active for session in app.made) == (last == "enable")
    assert app.c.speech_servers.row["state"] == ("ready" if last == "enable" else "stopped")


@pytest.mark.parametrize("source", ["mic", "speaker"])
@pytest.mark.parametrize("owner", ["settings", "other_source"])
def test_cancelled_enable_preserves_a_server_used_elsewhere(app, dispatch, monkeypatch, source, owner):
    if owner == "settings":
        app.c.speech_servers.row["state"] = "ready"
    else:
        other = "speaker" if source == "mic" else "mic"
        assert dispatch.main._call_handler(*queued_enable(dispatch, other)) == (True, 200)
    original = app.c._prepareRealtimeToggle

    def prepare(*args):
        result = original(*args)
        stop(dispatch, source)
        return result

    monkeypatch.setattr(app.c, "_prepareRealtimeToggle", prepare)
    assert_stale(dispatch.main._call_handler(*queued_enable(dispatch, source)), source)
    assert not app.c.speech_servers.stopped
    assert app.c.speech_servers.row["state"] == "ready"
    assert not any(session.source == source for session in app.made)


@pytest.mark.parametrize("source,direction", [("mic", "Send"), ("speaker", "Receive")])
def test_legacy_enable_ignores_realtime_stamp(app, dispatch, monkeypatch, source, direction):
    monkeypatch.setattr(module.sys, "platform", "win32")
    start = MagicMock(return_value=True)
    monkeypatch.setattr(app.c, "_startTranscription" + direction + "MessageLocked", start)
    request = queued_enable(dispatch, source)
    stop(dispatch, source)
    assert dispatch.main._call_handler(*request) == (True, 200)
    start.assert_called_once_with()
    app.service.recognizers.assert_not_called()
    assert not app.made and not app.c.speech_servers.started
