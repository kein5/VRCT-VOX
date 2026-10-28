"""Owned ASR capture; only private synthetic devices may be opened here."""

from contextlib import ExitStack
import importlib
import sys
import threading
import time

import pytest

from models.audio_routing.source_bridge import Endpoint

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="PipeWire capture")


def module():
    return importlib.import_module("models.transcription.capture_pipewire")


@pytest.mark.parametrize(
    "source,endpoint",
    [
        ("mic", Endpoint(1, 2, "safe", "Audio/Sink")),
        ("speaker", Endpoint(1, 2, "safe", "Audio/Source")),
        ("default", Endpoint(1, 2, "safe", "Audio/Source")),
        ("mic", Endpoint(1, 2, "", "Audio/Source")),
        ("mic", Endpoint(1, 2, "vrct.managed.mic", "Audio/Source")),
        ("mic", Endpoint(1, 2, "vrct.source-bridge.test", "Audio/Source")),
        ("mic", Endpoint(1, 2, "vrct.asr.capture.test", "Audio/Source")),
        ("mic", Endpoint(True, 2, "safe", "Audio/Source")),
        ("mic", Endpoint(1, 2**64, "safe", "Audio/Source")),
    ],
)
def test_invalid_identity_is_rejected_before_start(source, endpoint):
    with pytest.raises(ValueError, match="capture"):
        module().PipeWireCapture(
            endpoint, source, lambda frame: True, lambda code: None
        )


@pytest.mark.parametrize("kind", ["mic", "speaker"])
def test_owned_capture_delivers_20ms_frames_and_stop_discards_tail(kind):
    m = module()
    from tools.voice_acceptance import private_graph, loopback, nodes, wait_for
    from tools.voice_b_poc import Producer

    with private_graph(), ExitStack() as stack:
        loopback(stack, "vrct.capture.adapter")
        Producer(stack, "vrct.capture.adapter.sink", 440)
        choices = m.enumerate_endpoints(kind)
        name = "vrct.capture.adapter." + ("source" if kind == "mic" else "sink")
        endpoint = next(
            row["endpoint"] for row in choices if row["endpoint"].name == name
        )
        frames, errors = [], []
        capture = m.PipeWireCapture(
            endpoint, kind, lambda frame: frames.append(frame) or True, errors.append
        )
        try:
            capture.start()
            wait_for(lambda: len(frames) >= 10)
            assert all(
                len(f.audio.pcm) == 1920 and f.audio.sample_rate == 48000
                for f in frames
            )
            assert all(
                a.captured_ns < b.captured_ns for a, b in zip(frames, frames[1:])
            )
            assert any(any(f.audio.pcm) for f in frames)
            capture.stop()
            count = len(frames)
            time.sleep(0.1)
            assert len(frames) == count and errors == []
            assert not any(n.startswith("vrct.asr.capture.") for n in nodes())
            capture.stop()
            with pytest.raises(RuntimeError):
                capture.start()
        finally:
            capture.stop()


@pytest.mark.parametrize("fault", ["recreated", "removed", "consumer", "latency"])
def test_capture_stale_identity_disconnect_and_consumer_rejection_fail_closed(fault):
    m = module()
    from tools.voice_acceptance import (
        private_graph,
        loopback,
        nodes,
        stop_process,
        wait_for,
    )

    with private_graph(), ExitStack() as stack:
        device = loopback(stack, "vrct.capture.fault")
        endpoint = next(
            row["endpoint"]
            for row in m.enumerate_endpoints("mic")
            if row["endpoint"].name == "vrct.capture.fault.source"
        )
        errors, frames = [], []
        reject = threading.Event()

        def receive(frame):
            frames.append(frame)
            return not reject.is_set()

        capture = m.PipeWireCapture(endpoint, "mic", receive, errors.append)
        try:
            if fault == "recreated":
                stop_process(device)
                loopback(stack, "vrct.capture.fault")
                with pytest.raises(RuntimeError):
                    capture.start()
                assert frames == []
            else:
                capture.start()
                if fault == "removed":
                    stop_process(device)
                elif fault == "latency":
                    from tools.voice_b_poc import Producer
                    Producer(stack, "vrct.capture.fault.sink", 440)
                else:
                    reject.set()
                wait_for(lambda: bool(errors))
            capture.stop()
            assert len(errors) == 1 and errors[0].startswith("asr_capture_")
            assert not any(n.startswith("vrct.asr.capture.") for n in nodes())
        finally:
            capture.stop()


def test_stop_during_blocked_consumer_reaps_native_capture():
    m = module()
    from tools.voice_acceptance import private_graph, loopback, nodes, wait_for

    with private_graph(), ExitStack() as stack:
        loopback(stack, "vrct.capture.blocked")
        endpoint = next(
            row["endpoint"]
            for row in m.enumerate_endpoints("mic")
            if row["endpoint"].name == "vrct.capture.blocked.source"
        )
        block, entered, release = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def receive(frame):
            if block.is_set():
                entered.set()
                release.wait(3)
            return True

        capture = m.PipeWireCapture(endpoint, "mic", receive, lambda code: None)
        try:
            capture.start()
            block.set()
            assert entered.wait(1)
            began = time.monotonic()
            with pytest.raises(RuntimeError, match="consumer_busy"):
                capture.stop()
            assert time.monotonic() - began < 1
            wait_for(
                lambda: not any(n.startswith("vrct.asr.capture.") for n in nodes())
            )
        finally:
            release.set()
            capture.stop()


def test_stop_before_start_is_terminal_and_does_not_open_audio():
    m = module()
    capture = m.PipeWireCapture(
        Endpoint(1, 2, "safe", "Audio/Source"), "mic", lambda f: True, lambda e: None
    )
    capture.stop()
    with pytest.raises(RuntimeError):
        capture.start()
