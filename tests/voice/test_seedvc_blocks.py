# SPDX-License-Identifier: GPL-3.0-only
"""Converted audio must not survive a bypass, failed inference or stop."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import wave
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest


def session(engine):
    return importlib.import_module('integrations.seed_vc.blocks').BlockSession(engine)


class Engine:
    block_frame = 8

    def __init__(self):
        self.config = SimpleNamespace(function='vc')
        self.last_block_status = 'idle'
        self.entered, self.release = Event(), Event()
        self.release.set()
        self.fault = None

    def _process_block(self, data):
        self.entered.set()
        assert self.release.wait(2)
        if self.fault == 'exception':
            raise RuntimeError('inference broke')
        self.last_block_status = 'converted'
        if self.fault == 'mode_change':
            self.config.function = 'im'
        if self.fault == 'passthrough':
            return data.copy()
        if self.fault == 'nan':
            return np.full_like(data, np.nan)
        if self.fault == 'swallowed':
            self.last_block_status = 'inference_failed'
        return data * .5


@pytest.mark.parametrize('fault', ['exception', 'mode_change', 'passthrough', 'nan', 'swallowed'])
def test_bad_block_emits_nothing_and_failure_stays_closed(fault):
    engine = Engine()
    engine.fault = fault
    vc = session(engine)
    assert vc.convert(np.ones(8, dtype=np.float32)) is None
    assert vc.status == 'failed'
    engine.fault = None
    assert vc.convert(np.ones(8, dtype=np.float32)) is None
    assert vc.status == 'failed'


def test_bypass_rejected_before_calling_engine():
    engine = Engine()
    engine.config.function = 'im'
    vc = session(engine)
    assert vc.convert(np.ones(8, dtype=np.float32)) is None
    assert not engine.entered.is_set()
    assert vc.status == 'failed'


def test_stop_discards_inflight_result_and_cannot_be_overwritten():
    engine = Engine()
    engine.release.clear()
    vc = session(engine)
    results = []
    worker = Thread(target=lambda: results.append(vc.convert(np.ones(8, dtype=np.float32))))
    worker.start()
    assert engine.entered.wait(1)
    vc.stop()
    engine.release.set()
    worker.join(2)
    assert not worker.is_alive() and results == [None]
    assert vc.status == 'stopped'
    assert vc.convert(np.ones(8, dtype=np.float32)) is None


def test_valid_converted_block_retains_explicit_status():
    vc = session(Engine())
    np.testing.assert_array_equal(vc.convert(np.ones(8, dtype=np.float32)), np.full(8, .5))
    assert vc.status == 'converted'


def test_late_result_is_overload_even_when_inference_started_on_time():
    check = importlib.import_module('integrations.seed_vc.blocks').require_fresh_block
    check(1_000_000_000, 1_010_000_000, 80)
    with pytest.raises(TimeoutError, match='overload'):
        check(1_000_000_000, 1_170_000_000, 80)


@pytest.mark.skipif(not os.environ.get('VRCT_SEED_POC'), reason='consented local runtime/input required')
@pytest.mark.parametrize('profile', ['baseline', 'author', 'low', 'silent'])
def test_real_seed_blocks_convert_to_finite_non_passthrough_audio(tmp_path, profile):
    root = Path(os.environ['VRCT_SEED_POC']).resolve()
    source = root / 'private-inputs/input.wav'
    if profile == 'silent':
        source = tmp_path / 'silence.wav'
        with wave.open(str(source), 'wb') as output:
            output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            output.writeframes(b'\0\0' * 16000)
    result = subprocess.run([str(root / 'venv/bin/python'), '-m', 'integrations.seed_vc.convert',
        '--engine', str(root / 'engine'), '--assets', str(root / 'assets'),
        '--reference', str(root / 'private-inputs/reference.wav'),
        '--input', str(source), '--output', str(tmp_path / 'converted.wav'),
        '--report', str(tmp_path / 'converted.json'), '--profile', 'low' if profile == 'silent' else profile],
        capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    report = json.loads((tmp_path / 'converted.json').read_text())
    if profile == 'silent':
        assert report['converted_blocks'] == 0 and report['nonzero_samples'] == 0
    else:
        assert report['converted_blocks'] > 5 and report['nonzero_samples'] > 1000
    assert report['audio_device_module_loaded'] is False
    assert report['failure'] is None
