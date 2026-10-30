import gc
import json
from time import monotonic_ns
from uuid import uuid4


def test_opt_in_gc_spans_are_bounded_metadata_written_after_playback(tmp_path, monkeypatch):
    from models.tts import voice_trace as trace
    monkeypatch.setenv('VRCT_VOICE_GC_DIAGNOSTICS', '1')
    path = tmp_path / 'trace.jsonl'
    monkeypatch.setenv('VRCT_VOICE_TRACE', str(path))
    before = list(gc.callbacks)
    try:
        trace.install_gc_diagnostics()
        trace.install_gc_diagnostics()
        assert len(gc.callbacks) == len(before) + 1
        start = monotonic_ns()
        gc.collect()
        assert not path.exists()
        trace.write_voice_trace(str(uuid4()), start, None, 'completed')
        row = json.loads(path.read_text())
        assert row['gc_pauses'] and all(start <= a <= b for a, b, gen in row['gc_pauses'])
        assert all(type(gen) is int for a, b, gen in row['gc_pauses'])
        for _ in range(300):
            trace._gc_callback('start', {'generation': 0})
            trace._gc_callback('stop', {'generation': 0})
        assert len(trace._gc_events) == 256
    finally:
        gc.callbacks[:] = before
