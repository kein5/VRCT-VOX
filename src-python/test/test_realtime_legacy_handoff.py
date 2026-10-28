"""Real legacy ownership with simulated blocking cleanup; never opens devices."""

from threading import Event, Thread
from types import SimpleNamespace
import time

import pytest

import model as module
from model import MicSession, Model, SpeakerSession


@pytest.mark.parametrize("source,kind", [("mic", MicSession), ("speaker", SpeakerSession)])
@pytest.mark.parametrize("prior_stop", [False, True])
def test_handoff_retains_timed_out_recorder_until_stop_finishes(monkeypatch, source, kind, prior_stop):
    monkeypatch.setattr(module, "TRANSCRIPT_STOP_JOIN_TIMEOUT", 0.01)
    release, done = Event(), Event()
    calls = []

    def stop(**kwargs):
        calls.append(kwargs)
        release.wait(2)
        done.set()

    session = kind()
    session.features = {"transcript", "energy"}
    session._recorder = SimpleNamespace(resume=lambda: None, stop=stop)
    app = object.__new__(Model)
    app.ensure_initialized = lambda: None
    setattr(app, "_" + source + "_session", session)
    try:
        if prior_stop:
            assert session._stop() is True
        assert app.stopCaptureForRealtime(source) is False
        assert app.stopCaptureForRealtime(source) is False
        assert len(calls) == 1  # Retry must not detach or duplicate cleanup.
        assert not session.features
        release.set()
        assert done.wait(1)
        deadline = time.monotonic() + 1
        while not app.stopCaptureForRealtime(source):
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        release.set()
        done.wait(1)


def test_dead_cleanup_thread_with_error_is_not_successful_handoff(monkeypatch):
    monkeypatch.setattr(module, "TRANSCRIPT_STOP_JOIN_TIMEOUT", 0.05)
    session = MicSession()

    def fail(**kwargs):
        raise RuntimeError("private driver failure")

    session._recorder = SimpleNamespace(resume=lambda: None, stop=fail)
    assert session.stop_for_handoff() is False
    assert session.stop_for_handoff() is False


def test_handoff_waits_for_timed_out_legacy_result_worker(monkeypatch):
    monkeypatch.setattr(module, "TRANSCRIPT_STOP_JOIN_TIMEOUT", 0.01)

    class Worker(Thread):
        def stop(self):
            pass

    monkeypatch.setattr(module, "threadFnc", Worker)
    release = Event()
    worker = Worker(target=lambda: release.wait(2))
    session = MicSession()
    session._print_transcript = worker
    worker.start()
    try:
        assert session.stop_for_handoff() is False
        assert session.stop_for_handoff() is False
        release.set()
        worker.join(1)
        assert session.stop_for_handoff() is True
    finally:
        release.set()
        worker.join(1)
