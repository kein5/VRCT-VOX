"""Signal/measurement contracts; no PipeWire, models, or physical devices needed."""
from contextlib import contextmanager
import json
import math
import struct
from unittest.mock import MagicMock

import pytest

from tools import voice_b_poc as poc


def signal(*frequencies):
    return struct.pack('<960h', *(round(sum(2048 * math.sin(2 * math.pi * f * n / 48000)
                                            for f in frequencies)) for n in range(960)))


@pytest.mark.parametrize('frequencies', [(440,), (880,), (1760,), (440, 880), ()])
def test_frequency_presence_and_split_bytes(frequencies):
    observer = poc.ToneObservation()
    pcm = signal(*frequencies)
    observer.feed(pcm[:33], 1)
    assert observer.snapshot()['frames'] == 0
    observer.feed(pcm[33:], 20_000_000)
    state = observer.snapshot()
    assert state['frames'] == 1
    assert {int(f) for f, n in state['detected_frames'].items() if n} == set(frequencies)
    assert not any(isinstance(value, bytes) for value in state.values())


def test_settled_requires_continuous_fresh_reader_and_tracks_both_paths():
    observer = poc.ToneObservation()
    observer.feed(signal(440, 880), 20_000_000)
    for ms in range(40, 260, 20):
        observer.feed(signal(440), ms * 1_000_000)
    assert observer.settled(20_000_000, absent=(880,), present=(440,), duration_ms=200,
                            now_ns=240_000_000) == 40_000_000
    assert observer.settled(20_000_000, absent=(440,), duration_ms=200,
                            now_ns=240_000_000) is None
    assert observer.settled(20_000_000, absent=(880,), duration_ms=200,
                            now_ns=1_000_000_000) is None  # Dead reader is not silence.
    observer.feed(signal(440), 1_000_000_000)
    assert observer.settled(20_000_000, absent=(880,), duration_ms=200,
                            now_ns=1_000_000_000) is None  # Missing capture interval.


def test_global_silence_rejects_unclassified_audio():
    observer = poc.ToneObservation()
    for ms in range(20, 260, 20):
        observer.feed(signal(3000), ms * 1_000_000)
    assert observer.settled(1, silent=True, duration_ms=200, now_ns=240_000_000) is None


def test_mute_hold_rejects_even_a_transient_burst(monkeypatch):
    observer = poc.ToneObservation()
    observer.feed(signal(880), 20_000_000)
    observer.feed(signal(), 40_000_000)
    monkeypatch.setattr(poc, 'settled', lambda *a, **kw: 40_000_000)
    with pytest.raises(RuntimeError, match='mute_hold_leaked_audio'):
        poc.confirm_mute_hold(observer, 1, 0)


def test_partial_failure_report_survives_cleanup(tmp_path, monkeypatch):
    cleaned = []

    @contextmanager
    def graph():
        try:
            raise TimeoutError('private_policy_not_ready')
            yield
        finally:
            cleaned.append(True)

    monkeypatch.setattr(poc, 'private_graph', graph)
    output = tmp_path / 'failed'
    assert poc.main(['--output', str(output), '--runs', '1']) == 1
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == 'failed'
    assert report['failure_code'] == 'private_policy_not_ready'
    assert report['real_vc_verified'] is False
    assert report['raw_audio_saved'] is False
    assert cleaned == [True]
    assert (output / 'timings.csv').is_file()


def test_evidence_directory_cannot_be_overwritten(tmp_path):
    with pytest.raises(FileExistsError):
        poc.main(['--output', str(tmp_path)])


@pytest.mark.parametrize('args', [['--runs', '0'], ['--soak-seconds', '-1']])
def test_invalid_limits_exit_before_opening_graph(tmp_path, args):
    with pytest.raises(SystemExit):
        poc.main(['--output', str(tmp_path / 'out'), *args])


def test_consumer_fault_rejects_stalled_live_processes(monkeypatch):
    """Exercise the fault harness itself, not only a helper's implementation."""
    def capture(*args, **kwargs):
        observer = poc.ToneObservation()
        observer.feed(signal(), 20_000_000)
        observer.process = MagicMock()
        observer.process.poll.return_value = None
        return observer

    for name in ('loopback', 'Producer', 'set_default', 'ready', 'stop_process'):
        monkeypatch.setattr(poc, name, MagicMock())
    monkeypatch.setattr(poc, 'nodes', lambda: {})
    monkeypatch.setattr(poc, 'ToneCapture', capture)
    monkeypatch.setattr(poc.time, 'sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='consumer_observation_missing'):
        poc.consumer_fault(MagicMock(), {}, 1)


def test_guard_rejects_a_gap_even_after_silent_recovery():
    observer = poc.ToneObservation()
    observer.feed(signal(), 20_000_000)
    observer.feed(signal(), 820_000_000)
    for ms in range(840, 3020, 20):
        observer.feed(signal(), ms * 1_000_000)
    assert observer.settled(0, silent=True, now_ns=3_000_000_000) is not None
    assert observer.snapshot()['nonzero_frames'] == 0
    with pytest.raises(RuntimeError, match='output_guard_capture_gap'):
        poc.validate_output_guard(observer.snapshot())


@pytest.mark.parametrize('exit_code,eof,error,expected', [
    (1, True, None, 'disconnected'), (1, False, None, 'missing'),
    (None, False, None, 'missing'), (1, True, 'OSError', 'missing'),
])
def test_disconnection_requires_observed_eof(exit_code, eof, error, expected):
    before = poc.ToneObservation().snapshot()
    after = {**before, 'reader_eof': eof, 'reader_error': error}
    assert poc.consumer_observation(before, after, exit_code, 1, 3_000_000_000) == expected


def test_live_consumer_requires_progress_and_no_missing_interval():
    observer = poc.ToneObservation()
    observer.feed(signal(), 20_000_000)
    before = observer.snapshot()
    for ms in range(40, 2520, 20):
        observer.feed(signal(1760), ms * 1_000_000)
    after = observer.snapshot()
    assert poc.consumer_observation(before, after, None, 30_000_000, 2_510_000_000) == 'live'
    after['capture_gaps_over_100ms'] += 1
    assert poc.consumer_observation(before, after, None, 30_000_000, 2_510_000_000) == 'missing'
