"""Catch stale latency samples, false completion and lost HTTP stream errors."""
import wave

import pytest

from models.tts.speechcpp_tts import CancelToken, SpeechError
from tools import live_tts_acceptance as probe


def test_first_signal_excludes_old_audio_and_quiet_frames():
    history = [(90, set(), True), (110, set(), False), (130, set(), True)]
    assert probe.first_signal(history, 100) == 130
    assert probe.first_signal(history, 140) is None
    assert probe.first_signal([], 100) is None


def test_outcome_requires_this_request_to_finish_with_no_queued_work():
    before = dict(completed=3, cancelled=1, errors=2, active=False, queued=0)
    after = dict(before, completed=4)
    probe.require_outcome(before, after, 'completed')
    for bad in [before, dict(after, errors=3), dict(after, active=True), dict(after, queued=1)]:
        with pytest.raises(RuntimeError):
            probe.require_outcome(before, bad, 'completed')
    probe.require_outcome(before, dict(before, cancelled=2), 'cancelled')
    probe.require_outcome(before, dict(before, errors=3), 'errors')


def test_pcm_tap_preserves_real_http_stream_and_saves_exact_reference(pcm_server, tmp_path):
    tap = probe.PCMTap(tmp_path)
    with pcm_server(chunks=(b'\x01', b'\x00\x02', b'\x00')) as (url, requests):
        frames = list(tap.provider(url).synthesize_stream('hello', 'none', 'ja', CancelToken()))
    assert b''.join(frame.pcm for frame in frames) == b'\x01\x00\x02\x00'
    assert requests[0][1]['input'] == 'hello'
    record = tap.records[0]
    assert record['complete'] is True
    assert record['started_ns'] <= record['first_pcm_ns'] <= record['finished_ns']
    with wave.open(str(tmp_path / record['wav']), 'rb') as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (48000, 1, 2)
        assert wav.readframes(10) == b'\x01\x00\x02\x00'


def test_pcm_tap_keeps_partial_audio_and_does_not_swallow_transport_failure(pcm_server, tmp_path):
    tap = probe.PCMTap(tmp_path)
    with pcm_server(chunks=(b'\x01\x00',), truncate=True) as (url, _):
        stream = tap.provider(url).synthesize_stream('hello', 'none', 'ja', CancelToken())
        assert next(stream).pcm == b'\x01\x00'
        with pytest.raises(SpeechError):
            list(stream)
    record = tap.records[0]
    assert record['complete'] is False
    assert record['error'] == 'transport_error'
    assert record['samples'] == 1


@pytest.mark.parametrize('values,accepted,p95', [
    ([80] * 29 + [120], True, 80),  # nearest-rank p95 is the 29th of 30
    ([80] * 28 + [120] * 2, False, 120),
    ([80] * 29 + [260], False, 80),  # worst budget still applies
    ([125], True, None),  # one trial does not assert a distribution target
])
def test_crash_budget_cannot_hide_slow_tail_in_passing_individual_cases(values, accepted, p95):
    cases = [{'name': f'server-crash-{i}', 'command_to_silence_ms': v} for i, v in enumerate(values)]
    result = probe.crash_budget(cases)
    assert result['met'] is accepted
    assert result['p95_ms'] == p95
