# SPDX-License-Identifier: GPL-3.0-only
"""Worker resampling/protocol using a fake model; no model acquisition."""

from types import SimpleNamespace
import time

import numpy as np
import pytest

from models.voice_conversion import protocol as p

# Run with the optional Seed interpreter; scipy is deliberately not an app dependency.
pytest.importorskip("scipy.signal", reason="optional Seed resampler runtime required")


class Engine:
    def __init__(self, mode="converted"):
        self.config = SimpleNamespace(samplerate=22050, function="vc")
        self.block_frame = 1764
        self.mode = self.last_block_status = mode
        self.inputs = []

    def _process_block(self, data):
        self.inputs.append(data)
        self.last_block_status = self.mode
        if self.mode == "bypass":
            self.config.function = "im"
        return np.zeros_like(data) if self.mode == "vad_silence" else data * 0.5


@pytest.mark.parametrize("mode", ["converted", "vad_silence"])
def test_worker_maps_one_48k_block_and_preserves_correlation(mode):
    from integrations.seed_vc.live_worker import convert_packet
    from integrations.seed_vc.blocks import BlockSession

    engine = Engine(mode)
    stamp = time.monotonic_ns() - 90_000_000
    info = dict(p.input_info("a" * 32, 0, stamp), pcm_bytes=p.PCM_BYTES)
    raw = b"\20\0" * 3840
    output, pcm = convert_packet(BlockSession(engine), info, raw, "a" * 32, 0)
    assert engine.inputs[0].shape == (1764,)
    assert p.require_output(output, pcm, info, raw, time.monotonic_ns()) == mode
    assert len(pcm) == 7680 and (any(pcm) if mode == "converted" else not any(pcm))


@pytest.mark.parametrize("fault", ["bypass", "failed", "stale", "future", "replay"])
def test_worker_rejects_bad_or_unconverted_packets(fault):
    from integrations.seed_vc.live_worker import convert_packet
    from integrations.seed_vc.blocks import BlockSession

    engine = Engine(fault if fault in ("bypass", "failed") else "converted")
    stamp = time.monotonic_ns() - 90_000_000
    if fault == "stale":
        stamp -= 500_000_000
    if fault == "future":
        stamp += 500_000_000
    info = dict(p.input_info("a" * 32, 0, stamp), pcm_bytes=p.PCM_BYTES)
    with pytest.raises((RuntimeError, ValueError)):
        convert_packet(
            BlockSession(engine),
            info,
            b"\1\0" * 3840,
            "a" * 32,
            1 if fault == "replay" else 0,
        )
    if fault in ("stale", "future", "replay"):
        assert engine.inputs == []
