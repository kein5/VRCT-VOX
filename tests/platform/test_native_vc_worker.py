"""Opt-in live external VC on synthetic private audio, with the approved runtime."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import time
import wave

import pytest

from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE
from models.audio_routing.source_bridge import select_source
from tools.voice_acceptance import graph_snapshot, loopback, private_graph, wait_for
from tools.voice_b_poc import ToneCapture, settled

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get("VRCT_TEST_LIVE_VC"),
    reason="approved Seed runtime and synthetic input required",
)


@pytest.mark.parametrize("end", ["stop", "worker_death"])
def test_live_seed_worker_to_private_source_stops_without_raw_fallback(
    tmp_path, monkeypatch, end
):
    from models.voice_conversion import seed_process
    from test_native_realtime import SyntheticProducer

    runtime = Path(os.environ["VRCT_SEED_POC"]).resolve()
    with wave.open(str(runtime / "private-inputs/input.wav")) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            48000,
            1,
            2,
        )
        pcm = wav.readframes(wav.getnframes())
    report = dict(
        status="failed",
        case=end,
        physical_capture=False,
        vrchat=False,
        real_seed=True,
        perceptual_quality=False,
        samples_are_percentiles=False,
        boundary="capture block end bound to successful OS write; private read stop",
        writes=[],
    )
    output = seed_process._output

    class Measured:
        def __init__(self, endpoint):
            self.inner = output(endpoint)

        def write(self, pcm, token):
            self.inner.write(pcm, token)
            report["writes"].append(
                {
                    "input_end_to_write_ms": (time.monotonic_ns() - token.end_ns) / 1e6,
                    "nonzero": any(pcm),
                }
            )

        def close(self, **kwargs):
            return self.inner.close(**kwargs)

    monkeypatch.setattr(seed_process, "_output", Measured)
    vc = None
    try:
        with (
            private_graph(
                config_fragment=ROOT / "config/pipewire/90-vrct-managed.conf"
            ),
            ExitStack() as stack,
        ):
            loopback(stack, "vrct.native.caption")
            producer = stack.enter_context(SyntheticProducer(pcm))
            input_observer = ToneCapture(stack, "vrct.native.caption.source")
            settled(
                input_observer, time.monotonic_ns(), "input_not_stable", silent=True
            )
            capture = ToneCapture(stack, SOURCE)
            gate = PipeWireGate()
            gate.set_muted(False, gate.inspect()["identity"])
            vc = seed_process.SeedProcess(
                {
                    "runtime": str(runtime),
                    "reference": str(runtime / "private-inputs/reference.wav"),
                }
            )
            stack.callback(vc.close)
            vc.start(
                source=select_source(graph_snapshot(), "vrct.native.caption.source")
            )
            wait_for(lambda: vc.health()["active"] or vc.health()["error"], timeout=65)
            assert vc.health()["active"], vc.health()
            settled(capture, time.monotonic_ns(), "ready_not_silent", silent=True)
            producer.play()
            wait_for(
                lambda: (
                    vc.health()["conversion_verified"]
                    and capture.snapshot()["nonzero_frames"] > 5
                )
                or vc.health()["error"],
                timeout=12,
            )
            assert vc.health()["conversion_verified"], vc.health()
            assert capture.snapshot()["nonzero_frames"] > 5
            before = time.monotonic_ns()
            if end == "stop":
                vc.stop()
            else:
                vc._child.kill()  # Fault injection only; native supervisor owns worker lifetime.
                wait_for(lambda: vc.health()["error"])
            assert vc.close(timeout=3)
            silent = settled(capture, before, "stopped_vc_not_silent", silent=True)
            # Input continues independently; it must never become a raw fallback.
            producer.play()
            settled(
                capture, time.monotonic_ns(), "raw_fallback_after_stop", silent=True
            )
            assert vc._child.poll() is not None
            report.update(
                status="passed",
                stop_to_silent_read_ms=(silent - before) / 1e6,
                after=vc.health(),
                capture=capture.snapshot(),
                silence_hold_ms=2000,
            )
    finally:
        if vc:
            report["last_health"] = vc.health()
        (tmp_path / "report.json").write_text(json.dumps(report, indent=2) + "\n")
