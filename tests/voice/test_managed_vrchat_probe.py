"""Reject incomplete proof of a daemon-owned microphone and durable mute."""
import json
import sys
import pytest
from tools import managed_vrchat_probe
from tools.managed_vrchat_probe import require_checkpoint, require_continuous_capture


def status(**changes):
    return dict({'ready': True, 'pending': False, 'observed_muted': True,
                 'requested_muted': True, 'error': None}, **changes)


def test_checkpoint_requires_native_identity_and_confirmed_mute():
    assert require_checkpoint((1, 5), (1, 5), status(), True)
    with pytest.raises(RuntimeError):
        require_checkpoint((1, 5), (1, 6), status(), True)
    with pytest.raises(RuntimeError):
        require_checkpoint((1, 5), (1, 5), status(observed_muted=False), True)


def test_pending_or_storage_failure_is_not_confirmed_mute():
    for s in [status(pending=True), status(ready=False), status(error='disk_full')]:
        with pytest.raises(RuntimeError):
            require_checkpoint((1, 5), (1, 5), s, True)
    with pytest.raises(RuntimeError):
        require_checkpoint((1, 5), (1, 5), status(), False)


def test_capture_gap_or_reader_exit_cannot_prove_held_silence():
    healthy = {'reader_error': None, 'reader_eof': False, 'capture_gaps_over_100ms': 0}
    require_continuous_capture(healthy)
    for failure in [{'reader_error': 'OSError'}, {'reader_eof': True},
                    {'capture_gaps_over_100ms': 1}]:
        with pytest.raises(RuntimeError):
            require_continuous_capture({**healthy, **failure})


def test_cleanup_failure_overrides_success_and_fails_the_command(monkeypatch, tmp_path):
    def failing_cleanup(args, report):
        report['status'] = 'passed'
        raise RuntimeError('cleanup_failed')
    monkeypatch.setattr(managed_vrchat_probe, 'run', failing_cleanup)
    output = tmp_path / 'result'
    argv = ['managed_vrchat_probe']
    for option in ('reference', 'state-file', 'window', 'socket', 'replay-sink',
                   'ready-image', 'recording-image'):
        argv.extend(['--' + option, 'unused'])
    monkeypatch.setattr(sys, 'argv', argv + ['--output', str(output)])
    assert managed_vrchat_probe.main() == 1
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == 'failed'
    assert report['failure'] == 'cleanup_failed'
