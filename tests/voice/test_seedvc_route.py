# SPDX-License-Identifier: GPL-3.0-only
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(not os.environ.get('VRCT_SEED_ROUTE_TEST'), reason='consented GPU and private PipeWire PoC')
def test_real_vc_route_closes_on_stop_bypass_failure_and_worker_death(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'integrations.seed_vc.acceptance',
        '--poc-root', os.environ['VRCT_SEED_POC'], '--output', str(tmp_path / 'result'),
        '--profile', os.environ.get('VRCT_SEED_PROFILE', 'baseline'),
        *(['--prime-route'] if os.environ.get('VRCT_SEED_PRIME') == '1' else [])],
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    report = json.loads((tmp_path / 'result/report.json').read_text())
    assert report['status'] == 'passed'
    assert {r['case'] for r in report['trials']} == {'stop', 'bypass', 'fault', 'death', 'hold', 'slow', 'control'}
    assert all(r['capture']['reader_error'] is None for r in report['trials'])
    assert all(r['capture']['capture_gaps_over_100ms'] == 0 for r in report['trials'])
    assert all(not r['bridge_after']['active'] for r in report['trials'])
    assert all(r['ready_silence_confirmed'] for r in report['trials'])
    assert next(r for r in report['trials'] if r['case'] == 'hold')['worker_reason'] == 'TimeoutError'
    assert next(r for r in report['trials'] if r['case'] == 'slow')['worker_reason'] == 'worker_overload'
    assert next(r for r in report['trials'] if r['case'] == 'control')['continued_without_stop'] is True
