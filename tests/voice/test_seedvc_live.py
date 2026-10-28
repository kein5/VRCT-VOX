"""Real child pipes with deterministic fake inference; no microphone or models."""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import time

import pytest

from models.audio_routing.source_bridge import Endpoint
from models.transcription.realtime_audio import CapturedAudio
from models.voice_events import AudioFrame
from tools.voice_acceptance import wait_for

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux VC adapter")

SOURCE = Endpoint(1, 20, "test.original", "Audio/Source")
SINK = Endpoint(1, 30, "vrct.managed.vc", "Audio/Sink")
RAW = b"\1\0" * 3840
WORKER = """
import sys, time
from models.voice_conversion import protocol as p
mode, session = sys.argv[1:]
if mode == 'load_stall': time.sleep(30)
out = sys.stdout.buffer
out.write(p.encode_packet(p.ready_info(session))); out.flush()
if mode == 'no_read': time.sleep(30)
while True:
    info, raw = p.read_packet(sys.stdin.buffer, timeout=30)
    if mode == 'stall': time.sleep(30)
    if mode == 'late': time.sleep(.2)
    if mode == 'eof': break
    state = 'vad_silence' if mode in ('silence', 'false_silence') else 'converted'
    pcm = bytes(len(raw)) if mode == 'silence' else b'\\2\\0'*(len(raw)//2)
    if mode == 'bypass': pcm = raw
    result = dict(info, type='output', state=state)
    if mode == 'wrong_session': result['session'] = 'f'*32
    out.write(p.encode_packet(result, pcm)); out.flush()
"""


@contextmanager
def fixture(
    tmp_path, monkeypatch, mode="converted", blocked_output=False, cleanup_error=False,
    capture_start_error=None,
):
    from models.voice_conversion import seed_process as m

    captures, children, sent, closed = [], [], [], []
    binding = [SINK]
    runtime = tmp_path / "runtime"
    for name in ["venv/bin", "engine", "assets"]:
        (runtime / name).mkdir(parents=True, exist_ok=True)
    (runtime / "venv/bin/python").touch()
    reference = tmp_path / "reference.wav"
    reference.touch()

    class Capture:
        def __init__(self, endpoint, source, on_audio, on_error):
            assert endpoint == SOURCE and source == "mic"
            self.on_audio, self.on_error = on_audio, on_error
            self.stopped = False
            captures.append(self)

        def start(self):
            if capture_start_error:
                from models.transcription.capture_pipewire import CaptureError
                raise CaptureError(capture_start_error)

        def request_stop(self):
            self.stopped = True

        def stop(self):
            self.stopped = True
            closed.append("capture")
            if cleanup_error:
                raise RuntimeError("consumer_busy")

    class Output:
        def write(self, pcm, token):
            if blocked_output:
                time.sleep(0.2)
            token.check()
            sent.append(pcm)

        def close(self, **kwargs):
            closed.append("output")

    def launch(runtime, reference, session):
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", WORKER, mode, session],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env={
                **__import__("os").environ,
                "PYTHONPATH": str(Path("src-python").resolve()),
            },
        )
        children.append(child)
        return child

    monkeypatch.setattr(m, "_launch", launch)
    monkeypatch.setattr(m, "PipeWireCapture", Capture)
    monkeypatch.setattr(m, "_binding", lambda source: binding[0])
    monkeypatch.setattr(m, "_output", lambda endpoint: Output())
    process = m.SeedProcess({"runtime": str(runtime), "reference": str(reference)})
    try:
        process.start(source=SOURCE)
        yield process, captures, children, sent, closed, binding
    finally:
        assert process.close(timeout=3) is (not cleanup_error), (
            "owned VC cleanup status wrong"
        )
        assert all(c.poll() is not None for c in children)


def send(capture, *, stale=False):
    stamp = time.monotonic_ns() - 90_000_000 - (500_000_000 if stale else 0)
    for i in range(4):
        capture.on_audio(
            CapturedAudio(
                AudioFrame(RAW[i * 1920 : (i + 1) * 1920], 48000),
                stamp + i * 20_000_000,
            )
        )


def ready(process, captures):
    wait_for(lambda: captures and process.health()["active"], timeout=3)


@pytest.mark.parametrize("fault", ["cancel", "expire"])
def test_vc_output_rechecks_stop_and_age_at_actual_write(monkeypatch, fault):
    """Force preemption after the last readiness check, without an audio device."""
    import os
    from types import SimpleNamespace
    from models.audio_routing.devices_pipewire import PipeWireOutput
    from models.tts.speechcpp_tts import CancelToken, SpeechError
    from models.voice_conversion import seed_process as m

    clock = [1_010_000_000]
    monkeypatch.setattr(m.time, "monotonic_ns", lambda: clock[0])
    token = CancelToken()
    guard = m._Deadline(token, 1_000_000_000)
    original_check, checks = guard.check, []

    def check_then_preempt():
        original_check()
        checks.append(True)
        if len(checks) == 2:
            if fault == "cancel":
                token.cancel()  # Stop wins immediately before the OS write.
            else:
                clock[0] += m.p.MAX_AGE_NS  # Scheduling pause beyond the budget.

    monkeypatch.setattr(guard, "check", check_then_preempt)
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    os.set_blocking(write_fd, False)
    pipe = os.fdopen(write_fd, "wb", buffering=0)
    output = PipeWireOutput.__new__(PipeWireOutput)
    output.process = SimpleNamespace(stdin=pipe, poll=lambda: None)
    try:
        error = SpeechError if fault == "cancel" else m.p.ProtocolError
        with pytest.raises(error, match="cancelled|vc_block_expired"):
            output.write(b"\x02\x00", guard)
        with pytest.raises(BlockingIOError):
            os.read(read_fd, 2)  # Nothing reached the actual kernel pipe.
    finally:
        pipe.close()
        os.close(read_fd)


def test_model_ready_is_not_conversion_and_stop_discards_old_capture(
    tmp_path, monkeypatch
):
    with fixture(tmp_path, monkeypatch) as (p, captures, children, sent, closed, _):
        ready(p, captures)
        assert not p.health()["conversion_verified"]
        send(captures[0])
        wait_for(lambda: len(sent) == 1)
        assert sent == [b"\2\0" * 3840]
        assert p.health()["conversion_verified"]
        p.stop()
        send(captures[0])
        assert p.close(timeout=3)
        assert len(sent) == 1 and captures[0].stopped
        assert set(closed) == {"capture", "output"}
        assert not p.health()["requested"] and not p.health()["conversion_verified"]


@pytest.mark.parametrize(
    "mode", ["bypass", "eof", "wrong_session", "false_silence", "late", "stall"]
)
def test_bad_worker_never_forwards_raw_and_requires_new_start(
    tmp_path, monkeypatch, mode
):
    with fixture(tmp_path, monkeypatch, mode) as (
        p,
        captures,
        children,
        sent,
        closed,
        _,
    ):
        ready(p, captures)
        send(captures[0])
        wait_for(lambda: p.health()["error"], timeout=3)
        assert not p.health()["active"] and sent == []
        with pytest.raises(RuntimeError, match="single_use"):
            p.start(source=SOURCE)


def test_silence_is_not_conversion_proof(tmp_path, monkeypatch):
    with fixture(tmp_path, monkeypatch, "silence") as (
        p,
        captures,
        children,
        sent,
        closed,
        _,
    ):
        ready(p, captures)
        send(captures[0])
        wait_for(lambda: sent)
        assert sent == [bytes(7680)] and not p.health()["conversion_verified"]


@pytest.mark.parametrize("source", ["callback", "start"])
@pytest.mark.parametrize("code", ["asr_capture_latency_changed", "asr_capture_helper_closed",
                                 "asr_capture_start_timeout", "private unknown error"])
def test_capture_diagnostics_reach_vc_only_as_fixed_codes(tmp_path, monkeypatch, source, code):
    with fixture(tmp_path, monkeypatch, capture_start_error=code if source == "start" else None) as (
        p, captures, children, sent, closed, _,
    ):
        if source == "callback":
            ready(p, captures)
            captures[0].on_error(code)
        wait_for(lambda: p.health()["error"])
        expected = code if code.startswith("asr_capture_") else "vc_capture_failed"
        assert p.health()["error"] == expected
        assert not p.health()["requested"] and sent == []


@pytest.mark.parametrize(
    "fault", ["overflow", "stale", "blocked_output", "replaced", "capture_error"]
)
def test_capture_or_output_fault_closes_session(tmp_path, monkeypatch, fault):
    if fault == "overflow":
        # Isolate queue overflow from the independent, tighter age guard.
        from models.voice_conversion import protocol

        monkeypatch.setattr(protocol, "MAX_AGE_NS", 1_000_000_000)
    with fixture(
        tmp_path,
        monkeypatch,
        "stall" if fault == "overflow" else "converted",
        blocked_output=fault == "blocked_output",
    ) as (p, captures, children, sent, closed, binding):
        ready(p, captures)
        if fault == "replaced":
            binding[0] = Endpoint(1, 31, SINK.name, SINK.media_class)
        elif fault == "capture_error":
            captures[0].on_error("asr_capture_endpoint_changed")
        else:
            send(captures[0], stale=fault == "stale")
            if fault == "overflow":
                for _ in range(3):
                    time.sleep(0.09)
                    send(captures[0])
        wait_for(lambda: p.health()["error"], timeout=3)
        assert sent == [] and not p.health()["requested"]
        if fault == "overflow":
            assert p.health()["error"] == "vc_capture_overrun"


def test_stop_while_model_loading_never_opens_capture(tmp_path, monkeypatch):
    with fixture(tmp_path, monkeypatch, "load_stall") as (
        p,
        captures,
        children,
        sent,
        closed,
        _,
    ):
        wait_for(lambda: children)
        before = time.monotonic()
        p.stop()
        assert time.monotonic() - before < 0.1
        assert p.close(timeout=2)
        assert captures == [] and sent == []


def test_incomplete_cleanup_cannot_be_reported_as_closed(tmp_path, monkeypatch):
    with fixture(tmp_path, monkeypatch, cleanup_error=True) as (
        p,
        captures,
        children,
        sent,
        closed,
        _,
    ):
        ready(p, captures)
        p.stop()
        assert p.close(timeout=3) is False
        assert p.health()["error"] == "vc_cleanup_failed"


def test_stop_while_worker_is_processing_rejects_pending_result(tmp_path, monkeypatch):
    with fixture(tmp_path, monkeypatch, 'late') as (p, captures, children, sent, closed, _):
        ready(p, captures)
        send(captures[0])
        p.stop()
        assert p.close(timeout=2)
        assert sent == []


def test_unread_worker_input_pipe_is_bounded_and_cancelled(tmp_path, monkeypatch):
    import fcntl
    with fixture(tmp_path, monkeypatch, 'no_read') as (p, captures, children, sent, closed, _):
        ready(p, captures)
        fcntl.fcntl(children[0].stdin.fileno(), fcntl.F_SETPIPE_SZ, 4096)
        send(captures[0])
        wait_for(lambda: p.health()['error'], timeout=1)
        assert p.health()['error'] == 'vc_block_expired'
        assert sent == []
