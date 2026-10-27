"""The acceptance harness must preserve failures and reject missing observations."""
from contextlib import contextmanager
import importlib
import json

import pytest


def module():
    return importlib.import_module('tools.source_bridge_acceptance')


@pytest.mark.parametrize('runs', ['0', '-1', '31'])
def test_bad_run_count_rejected_without_output(tmp_path, runs):
    destination = tmp_path / 'results'
    with pytest.raises(SystemExit):
        module().main(['--output', str(destination), '--runs', runs])
    assert not destination.exists()


def test_existing_output_never_overwritten(tmp_path):
    (tmp_path / 'report.json').write_text('keep')
    with pytest.raises(FileExistsError):
        module().main(['--output', str(tmp_path)])
    assert (tmp_path / 'report.json').read_text() == 'keep'


def test_partial_failure_saves_evidence_and_cleans_graph(tmp_path, monkeypatch):
    m, closed = module(), []

    @contextmanager
    def private_graph(**kwargs):
        try:
            yield object()
        finally:
            closed.append(True)

    def fail(stack, record):
        record['partial'] = 'evidence'
        raise RuntimeError('source_bridge_test_fault')

    monkeypatch.setattr(m, 'private_graph', private_graph)
    monkeypatch.setattr(m, 'exercise_trial', fail)
    out = tmp_path / 'results'
    assert m.main(['--output', str(out), '--runs', '1']) == 1
    data = json.loads((out / 'report.json').read_text())
    assert data['status'] == 'failed' and data['trials'][0]['partial'] == 'evidence'
    assert data['failure_code'] == 'source_bridge_test_fault'
    assert closed == [True]
    assert data['real_vc_verified'] is False and data['host_audio_changed'] is False
    assert data['raw_pcm_saved'] is False


@pytest.mark.parametrize('fault', ['stale', 'eof', 'error', 'gap', 'no_progress'])
def test_dead_or_missing_capture_is_not_silence(fault):
    before = {'frames': 100, 'capture_gaps_over_100ms': 0}
    after = {'frames': 200, 'capture_gaps_over_100ms': 0, 'last_read_ns': 1_000_000_000,
             'reader_error': None, 'reader_eof': False}
    if fault == 'stale':
        after['last_read_ns'] = 0
    elif fault == 'eof':
        after['reader_eof'] = True
    elif fault == 'error':
        after['reader_error'] = 'OSError'
    elif fault == 'gap':
        after['capture_gaps_over_100ms'] = 1
    else:
        after['frames'] = 100
    with pytest.raises(RuntimeError, match='capture'):
        module().check_capture(before, after, now_ns=1_010_000_000)


def test_fresh_continuous_capture_accepted():
    module().check_capture({'frames': 10, 'capture_gaps_over_100ms': 0},
        {'frames': 200, 'capture_gaps_over_100ms': 0, 'last_read_ns': 1_000_000_000,
         'reader_error': None, 'reader_eof': False}, now_ns=1_010_000_000)
