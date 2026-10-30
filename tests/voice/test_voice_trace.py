"""Diagnostic failure must never become a speech/legacy-delivery failure."""
import json
import os
import stat
from time import monotonic_ns
from uuid import uuid4

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import SpeechMessageEvent
from test_scheduler import until


def run_message(url, sink, *, event_id=None):
    bus = VoiceEventBus(VoiceSettings(mode="original", output_device="test",
                                     japanese_url=url), router=AudioRouter(lambda *args: sink))
    event = SpeechMessageEvent(event_id or str(uuid4()), "chat", "PRIVATE TEXT",
                               source_language="ja")
    assert bus.publish(event)
    until(lambda: bus.status()["completed"] + bus.status()["cancelled"] + bus.status()["errors"] == 1)
    assert bus.close()
    return event, bus.status()


class ObservedSink:
    def __init__(self, path, behavior="normal"):
        self.path, self.behavior = path, behavior
        self.first_write_ns = None
        self.closed_ns = None

    def write(self, pcm, token):
        assert not self.path.exists(), "trace IO must happen after playback"
        if self.behavior == "error":
            raise OSError("PRIVATE EXCEPTION")
        if self.behavior == "cancel":
            token.cancel()
            token.check()
        if any(pcm) and self.first_write_ns is None:
            self.first_write_ns = monotonic_ns()

    def close(self, **kwargs):
        assert not self.path.exists(), "trace IO must happen after close"
        self.closed_ns = monotonic_ns()


@pytest.mark.parametrize("behavior,pcm,outcome", [
    ("normal", b"\0" * 960 + b"\1\0" * 960, "completed"),
    ("normal", b"\0" * 960, "completed"),
    ("cancel", b"\1\0" * 960, "cancelled"),
    ("error", b"\1\0" * 960, "error"),
], ids=["leading_silence", "all_silent", "cancel_before_write", "write_error"])
def test_opt_in_trace_records_first_nonzero_write_after_playback(
        tmp_path, monkeypatch, pcm_server, behavior, pcm, outcome):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("VRCT_VOICE_TRACE", str(path))
    sink = ObservedSink(path, behavior)
    with pcm_server(chunks=(pcm,)) as (url, requests):
        event, _ = run_message(url, sink)
    assert len(requests) == 1
    assert path.exists(), "opt-in trace missing"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"schema", "event_id", "started_ns", "first_write_ns", "sample_rate", "outcome"}
    assert row["schema"] == 1 and row["event_id"] == event.event_id
    assert row["started_ns"] == event.timestamp_ns and row["outcome"] == outcome
    if sink.first_write_ns is None:
        assert row["first_write_ns"] is None and row["sample_rate"] is None
    else:
        assert sink.first_write_ns <= row["first_write_ns"] <= sink.closed_ns
        assert row["sample_rate"] == 48000
    assert "PRIVATE" not in path.read_text() and url not in path.read_text()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_trace_disabled_by_default(tmp_path, monkeypatch, pcm_server):
    monkeypatch.delenv("VRCT_VOICE_TRACE", raising=False)
    path = tmp_path / "trace.jsonl"
    with pcm_server() as (url, _):
        _, status = run_message(url, ObservedSink(path))
    assert status["completed"] == 1 and not path.exists()


def test_trace_does_not_record_arbitrary_event_id(tmp_path, monkeypatch, pcm_server):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("VRCT_VOICE_TRACE", str(path))
    with pcm_server() as (url, _):
        run_message(url, ObservedSink(path), event_id="PRIVATE USER SUPPLIED ID")
    assert path.exists(), "opt-in trace missing"
    assert json.loads(path.read_text())["event_id"] is None
    assert "PRIVATE" not in path.read_text()


@pytest.mark.parametrize("target", ["directory", "missing_parent", "full", "fifo"])
def test_bad_trace_destination_leaves_worker_healthy(tmp_path, monkeypatch, pcm_server, target):
    path = tmp_path / "trace"
    if target == "directory":
        path.mkdir()
    elif target == "missing_parent":
        path = path / "missing" / "trace"
    elif target == "full":
        with path.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024)
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("FIFO is a Unix failure mode")
        os.mkfifo(path)
    monkeypatch.setenv("VRCT_VOICE_TRACE", str(path))
    # Sentinel path differs from the invalid destination; playback may proceed.
    with pcm_server() as (url, _):
        _, status = run_message(url, ObservedSink(tmp_path / "absent"))
    assert status["completed"] == 1 and status["errors"] == 0
    if target == "full":
        assert path.stat().st_size == 8 * 1024 * 1024
