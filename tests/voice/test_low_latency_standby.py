"""Standby never creates an output route or reads user text."""

from threading import Event
import time
import pytest
from models.speech_server.settings import normalize_settings
from tools.voice_acceptance import wait_for


def test_standby_is_opt_in_and_only_for_japanese_gpu_profile():
    value = normalize_settings({})
    assert all(not row["low_latency"] for row in value["profiles"].values())
    value["profiles"]["japanese"]["low_latency"] = True
    assert normalize_settings(value)["profiles"]["japanese"]["low_latency"]
    for profile, key, bad in [
        ("asr", "low_latency", True),
        ("multilingual", "low_latency", True),
        ("japanese", "low_latency", "true"),
        ("japanese", "low_latency", 1),
    ]:
        other = normalize_settings({})
        other["profiles"][profile][key] = bad
        with pytest.raises(ValueError):
            normalize_settings(other)


def test_periodic_discard_and_stop_interrupts_owned_request():
    from models.speech_server.low_latency import LowLatencyStandby

    calls = []
    blocked = Event()

    def synthesize(token):
        calls.append(token)
        if len(calls) > 1:
            blocked.set()
            token.wait(2)
            token.check()
        yield object()  # No output interface is needed; each frame is discarded.

    worker = LowLatencyStandby(
        "http://127.0.0.1:1", synthesize=synthesize, interval=0.01
    )
    try:
        worker.start()
        assert blocked.wait(1)
        assert worker.health()["completed"] == 1
        assert worker.close(1)
        assert calls[-1].is_set()
        count = len(calls)
        time.sleep(0.03)
        assert len(calls) == count and worker.health()["state"] == "stopped"
    finally:
        worker.close()


def test_failure_is_visible_and_does_not_spin_or_emit_audio():
    from models.speech_server.low_latency import LowLatencyStandby

    def fail(token):
        raise RuntimeError("private-data-must-not-escape")

    worker = LowLatencyStandby("http://127.0.0.1:1", synthesize=fail, interval=0.01)
    try:
        worker.start()
        wait_for(lambda: worker.health()["state"] == "failed", timeout=1)
        assert worker.health()["error_code"] == "speech_server_low_latency_failed"
        assert "private" not in str(worker.health())
    finally:
        assert worker.close()
