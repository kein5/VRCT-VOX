"""Optional Torch tests with synthetic inference, never downloaded weights."""

from types import SimpleNamespace
import time

import numpy as np
import pytest

from models.voice_conversion import protocol as p

torch = pytest.importorskip("torch", reason="optional VC runtime")
pytest.importorskip("torchaudio", reason="optional VC resampler")


class Engine:
    def __init__(self, fault=None, rate=40000):
        self.device = "cpu"
        self.tgt_sr, self.version, self.if_f0 = rate, "v2", 1
        self.cache_pitch = torch.zeros(1024)
        self.cache_pitchf = torch.zeros(1024)
        self.index_rate = 0
        self.fault, self.calls = fault, []

    def infer(self, data, block, skip, length, method):
        self.calls.append((data.clone(), block, skip, length, method))
        if self.fault == "raises":
            raise RuntimeError("engine failed")
        count = self.tgt_sr * length // 100
        output = 0.2 * torch.cos(torch.arange(count) * (2 * np.pi * 220 / self.tgt_sr))
        if self.fault == "short":
            output = output[:3]
        if self.fault == "nan":
            output[0] = float("nan")
        if self.fault == "shape":
            output = output[None, :]
        return output


@pytest.mark.parametrize("rate", [32000, 40000, 48000])
def test_streaming_frames_use_history_and_reset_warmup_state(rate):
    from integrations.rvc.blocks import BlockSession

    engine = Engine(rate=rate)
    session = BlockSession(engine)
    wave = np.sin(np.arange(p.FRAMES, dtype=np.float32) * 0.02) * 0.1
    first = session.convert(wave)
    second = session.convert(wave)
    assert first.shape == second.shape == (p.FRAMES,)
    assert np.isfinite(second).all() and np.max(np.abs(second)) > 0.1
    a, b = engine.calls
    assert a[0].shape == b[0].shape == (34080,)
    assert a[1:] == (1280, 200, 13, "rmvpe")
    assert torch.count_nonzero(b[0][:-1280]) > torch.count_nonzero(a[0][:-1280])
    engine.cache_pitch.fill_(80)
    engine.cache_pitchf.fill_(220)
    session.reset()
    after = session.convert(wave)
    assert np.allclose(first, after)
    assert not torch.any(engine.cache_pitch) and not torch.any(engine.cache_pitchf)


@pytest.mark.parametrize("fault", ["short", "nan", "shape", "raises"])
def test_malformed_inference_never_reaches_output(fault):
    from integrations.rvc.blocks import BlockSession

    with pytest.raises((ValueError, RuntimeError)):
        BlockSession(Engine(fault)).convert(np.zeros(p.FRAMES, np.float32))


@pytest.mark.parametrize(
    "change", [dict(tgt_sr=44100), dict(version="v3"), dict(if_f0=2)]
)
def test_unsupported_engine_format_rejected(change):
    from integrations.rvc.blocks import BlockSession

    engine = Engine()
    engine.__dict__.update(change)
    with pytest.raises(ValueError, match="vc_engine_format_invalid"):
        BlockSession(engine)


def test_packet_deadline_is_checked_before_and_after_inference(monkeypatch):
    from integrations.rvc.live_worker import convert_packet

    clock = [2_000_000_000]
    monkeypatch.setattr(time, "monotonic_ns", lambda: clock[0])
    info = dict(p.input_info("a" * 32, 0, clock[0] - 90_000_000), pcm_bytes=p.PCM_BYTES)
    raw = b"\x10\x00" * p.FRAMES

    class VC:
        def convert(self, data):
            assert data.shape == (p.FRAMES,)
            return data * 0.5

    result, pcm = convert_packet(VC(), info, raw, "a" * 32, 0)
    assert result["state"] == "converted" and pcm == b"\x08\x00" * p.FRAMES

    class Slow:
        def convert(self, data):
            clock[0] += p.MAX_AGE_NS
            return data * 0.5

    with pytest.raises(p.ProtocolError, match="vc_block_expired"):
        convert_packet(Slow(), info, raw, "a" * 32, 0)

    class Forbidden:
        def convert(self, data):
            pytest.fail("expired input reached inference")

    with pytest.raises(p.ProtocolError, match="vc_block_expired"):
        convert_packet(Forbidden(), info, raw, "a" * 32, 0)


@pytest.mark.parametrize("fault", ["negative", "zero", "nan", "raises"])
def test_upstream_swallowed_index_error_is_latched(fault):
    from integrations.rvc.loader import CheckedIndex

    class Index:
        def search(self, values, k):
            if fault == "raises":
                raise RuntimeError("faiss failed")
            score = np.ones((1, 8), np.float32)
            ix = np.zeros((1, 8), np.int64)
            if fault == "negative":
                ix[0, 0] = -1
            if fault == "zero":
                score[0, 0] = 0
            if fault == "nan":
                score[0, 0] = np.nan
            return score, ix

    checked = CheckedIndex(Index(), 8)
    try:  # Matches upstream's broad exception handling.
        checked.search(np.zeros((1, 768), np.float32), k=8)
    except Exception:
        pass
    with pytest.raises(ValueError, match="vc_index_failed"):
        checked.require_success()


def test_incomplete_checkpoint_cannot_keep_random_parameters():
    from integrations.rvc.loader import load_complete_state

    net = torch.nn.Linear(2, 2)
    weights = net.state_dict()
    with pytest.raises(ValueError, match="vc_checkpoint_incomplete"):
        load_complete_state(net, {"weight": weights["weight"]})
    load_complete_state(net, weights)


def test_partial_constructor_state_is_not_ready():
    from integrations.rvc.loader import require_engine

    with pytest.raises(ValueError, match="vc_engine_initialization_failed"):
        require_engine(SimpleNamespace(device="cpu", model=object(), net_g=None))


def test_requested_index_failure_blocks_audio_even_if_upstream_continues():
    from integrations.rvc.blocks import BlockSession
    from integrations.rvc.loader import CheckedIndex

    engine = Engine()
    engine.index_rate = 0.5
    engine.index = CheckedIndex(None, 8)
    # A swallowed exception leaves no successful search, despite valid PCM.
    with pytest.raises(ValueError, match="vc_index_failed"):
        BlockSession(engine).convert(np.zeros(p.FRAMES, np.float32))


def test_upstream_post_search_blending_failure_cannot_be_swallowed(monkeypatch):
    from pathlib import Path
    import traceback
    from integrations.rvc import loader

    class Index:
        def search(self, values, k):
            return np.ones((len(values), k), np.float32), np.zeros(
                (len(values), k), np.int64
            )

    engine = SimpleNamespace(
        index=loader.CheckedIndex(Index(), 8),
        index_rate=0.5,
        big_npy=np.ones((8, 768), np.float32),
        config=SimpleNamespace(is_half=False),
        device="cpu",
    )
    module = SimpleNamespace(traceback=traceback)

    # Emulate a device/conversion error after successful FAISS search.
    def fail_conversion(*args, **kwargs):
        raise RuntimeError("injected post-search allocation failure")

    monkeypatch.setattr(torch, "from_numpy", fail_conversion)
    configure = getattr(loader, "enforce_retrieval_errors", lambda module: None)
    configure(module)
    scope = dict(
        self=engine,
        feats=torch.ones(1, 8, 768),
        skip_head=0,
        report_status=True,
        np=np,
        torch=torch,
        traceback=module.traceback,
        i18n=lambda x: x,
        printt=lambda *args: None,
    )
    code = (Path(__file__).parent / "fixtures/rvc_retrieval.py").read_text()
    with pytest.raises(ValueError, match="vc_index_failed"):
        exec(compile(code, "pinned-rvc-retrieval", "exec"), scope)
    assert engine.index.calls == 1  # Search succeeded; the failure occurred afterward.


def test_fixed_worker_main_warms_up_then_streams_real_pipe_packets(tmp_path):
    import os
    import subprocess
    import sys

    script = """
import sys
sys.path.insert(0, 'tests/voice')
from test_rvc_worker import Engine
from integrations.rvc import loader, live_worker
loader.create_engine = lambda *args: Engine()
sys.argv = ['rvc', '--engine', '/fake', '--assets', '/fake', '--model', '/fake.pth', '--session', 'a'*32]
live_worker.main()
"""
    with (tmp_path / "worker.log").open("wb") as log:
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            bufsize=0,
            env={**os.environ, "PYTHONPATH": os.path.abspath("src-python")},
        )
        try:
            info, raw = p.read_packet(child.stdout, timeout=10)
            p.require_ready(info, raw, "a" * 32, engine="rvc")
            info = dict(
                p.input_info("a" * 32, 0, time.monotonic_ns() - 90_000_000),
                pcm_bytes=p.PCM_BYTES,
            )
            raw = b"\x10\x00" * p.FRAMES
            child.stdin.write(p.encode_packet(info, raw))
            result, output = p.read_packet(child.stdout, timeout=3)
            assert (
                p.require_output(result, output, info, raw, time.monotonic_ns())
                == "converted"
            )
            child.stdin.close()
            child.wait(3)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(3)
            child.stdout.close()
            if not child.stdin.closed:
                child.stdin.close()
