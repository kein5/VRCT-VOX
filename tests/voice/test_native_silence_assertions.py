"""Exercise the native harness's actual silence gate without GUI or audio devices."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.managed_vrchat_probe import require_continuous_capture
from tools.voice_b_poc import FRAME, ToneObservation


@pytest.mark.parametrize('fault', [None, 'burst', 'gap', 'eof'])
def test_no_output_case_rejects_transient_audio_and_capture_loss(fault):
    source = Path(__file__).parents[1] / 'platform/test_native_low_latency_controls.py'
    function = next(n for n in ast.walk(ast.parse(source.read_text()))
                    if isinstance(n, ast.FunctionDef) and n.name == 'silence')
    monitor = ToneObservation()
    monitor.feed(bytes(FRAME * 2), 20_000_000)
    snapshot = monitor.snapshot
    monitor.snapshot = lambda: {**snapshot(), 'reader_eof': fault == 'eof', 'reader_error': None}
    monitor.process = SimpleNamespace(poll=lambda: None)
    monitor.thread = SimpleNamespace(is_alive=lambda: True)
    now = [30_000_000]

    def action():
        for ms in range(40, 2420, 20):
            if fault == 'gap' and 40 <= ms < 200:
                continue
            pcm = b'\xff\x00' * FRAME if fault == 'burst' and ms < 240 else bytes(FRAME * 2)
            monitor.feed(pcm, ms * 1_000_000)
        now[0] = 2_410_000_000

    def settled(capture, start, code, **kwargs):
        result = capture.settled(start, now_ns=now[0], **kwargs)
        # The old gate accepts both a short burst and a lost interval once a
        # sufficiently long quiet tail follows. These cases need the new gate.
        assert result is not None, code
        return result

    env = dict(monitor=monitor, traces=lambda: [], report={'cases': []}, settled=settled,
               require_continuous_capture=require_continuous_capture,
               time=SimpleNamespace(monotonic_ns=lambda: now[0]))
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
    if fault:
        with pytest.raises((AssertionError, RuntimeError)):
            env['silence']('no_new_output', action)
        assert env['report']['cases'] == []
    else:
        env['silence']('no_new_output', action)
        assert len(env['report']['cases']) == 1
