# SPDX-License-Identifier: GPL-3.0-only
"""Local-only PoC resolution rejects incomplete or substituted model inputs."""
import importlib
from pathlib import Path
from types import SimpleNamespace
import wave
import os
import json
import subprocess

import pytest

from test_seedvc_artifacts import manifest, fetch
from tools.seedvc_artifacts import fetch_artifacts


def module():
    return importlib.import_module('integrations.seed_vc.offline')


def test_assets_resolve_only_verified_existing_manifest_entries(tmp_path):
    data = manifest()
    result = fetch_artifacts(data, tmp_path, opener=fetch(b'data', []))
    assets = module().OfflineAssets(data, tmp_path)
    assert assets.file('owner/model', 'model.bin') == Path(result['files'][0]['path'])
    for repo, name in [('unknown/model', 'model.bin'), ('owner/model', 'extra.bin'), ('owner/model', '../model.bin')]:
        with pytest.raises(ValueError, match='unapproved_artifact'):
            assets.file(repo, name)


@pytest.mark.parametrize('fault', ['missing', 'changed'])
def test_missing_or_changed_checkpoint_cannot_initialize_assets(tmp_path, fault):
    data = manifest()
    result = fetch_artifacts(data, tmp_path, opener=fetch(b'data', []))
    path = Path(result['files'][0]['path'])
    if fault == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'evil')
    with pytest.raises((FileNotFoundError, ValueError)):
        module().OfflineAssets(data, tmp_path)


@pytest.mark.parametrize('duration', [.5, 31])
def test_reference_outside_supported_length_is_rejected(tmp_path, duration):
    path = tmp_path / 'voice.wav'
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\0\0' * int(duration * 16000))
    with pytest.raises(ValueError, match='reference_duration'):
        module().validate_reference(path)


def test_reference_remote_or_missing_path_rejected():
    with pytest.raises(ValueError, match='reference_local_file'):
        module().validate_reference('https://example.test/voice.wav')


def test_reference_metadata_has_no_transcript_or_original_path(tmp_path):
    path = tmp_path / 'private-name.wav'
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\1\0' * 16000)
    result = module().validate_reference(path)
    assert result['duration_s'] == 1 and result['sample_rate'] == 16000
    assert len(result['sha256']) == 64
    assert 'private-name' not in repr(result) and 'path' not in result


@pytest.mark.parametrize('actual', [{}, {'weight': (3, 2)}, {'other': (2, 2)}])
def test_missing_or_wrong_shape_weights_never_pass_completeness(actual):
    expected = {'weight': SimpleNamespace(shape=(2, 2))}
    supplied = {key: SimpleNamespace(shape=shape) for key, shape in actual.items()}
    with pytest.raises(ValueError, match='checkpoint_incomplete'):
        module().require_complete_state(expected, supplied)


def test_compatible_weights_pass_without_claiming_unused_parameters_loaded():
    expected = {'weight': SimpleNamespace(shape=(2, 2))}
    supplied = {**expected, 'unused_training_head': SimpleNamespace(shape=(3,))}
    assert module().require_complete_state(expected, supplied) == {'required': 1, 'unused': 1}


def test_campplus_key_migration_preserves_values_and_rejects_collisions():
    loader = importlib.import_module('integrations.seed_vc.loader')
    original = {'xvector.dense.weight': object(), 'xvector.stats.value': object(),
                'head.weight': object()}
    assert loader.remap_campplus_state(original) == {
        'dense.weight': original['xvector.dense.weight'],
        'stats.value': original['xvector.stats.value'], 'head.weight': original['head.weight']}
    with pytest.raises(ValueError, match='checkpoint_duplicate_key'):
        loader.remap_campplus_state({'dense.weight': object(), 'xvector.dense.weight': object()})


@pytest.mark.skipif(not os.environ.get('VRCT_SEED_POC'), reason='consented local assets and CUDA runtime required')
def test_five_real_models_load_and_vad_processes_chunks_offline(tmp_path):
    root = Path(os.environ['VRCT_SEED_POC']).resolve()
    report = tmp_path / 'load.json'
    result = subprocess.run([
        str(root / 'venv/bin/python'), '-m', 'integrations.seed_vc.smoke',
        '--engine', str(root / 'engine'), '--assets', str(root / 'assets'),
        '--reference', str(root / 'private-inputs/reference.wav'), '--report', str(report),
    ], capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, (result.stdout + result.stderr)[-8000:]
    data = json.loads(report.read_text())
    assert data['model_ready'] is True and data['converted'] is False
    assert set(data['checkpoints']) == {'seed', 'campplus', 'hift', 'xlsr', 'vad'}
    assert data['vad_chunks'] > 5 and data['vad_segments'] > 0
    assert data['audio_device_module_loaded'] is False


@pytest.mark.skipif(not os.environ.get('VRCT_SEED_POC'), reason='isolated torch runtime required')
def test_seed_buffer_migration_is_limited_and_validates_values():
    root = Path(os.environ['VRCT_SEED_POC']).resolve()
    code = '''
import math
import torch
from integrations.seed_vc.loader import migrate_seed_state
freq = 'estimator.t_embedder.freqs'
pos = 'estimator.input_pos'
expected = {freq: torch.exp(-math.log(10000) * torch.arange(128, dtype=torch.float32) / 128),
            pos: torch.arange(16384), 'learned.weight': torch.ones(2, 2)}
legacy = {pos: torch.arange(8192), 'learned.weight': torch.full((2, 2), 3.)}
result = migrate_seed_state(expected, legacy)
assert torch.equal(result[freq], expected[freq])
assert torch.equal(result[pos], expected[pos])
assert torch.equal(result['learned.weight'], legacy['learned.weight'])
for bad in [dict(legacy, **{pos: torch.zeros(8192, dtype=torch.long)}),
            dict(legacy, **{pos: torch.arange(8192, dtype=torch.float32)}),
            dict(legacy, **{freq: torch.zeros(128)}),
            {pos: legacy[pos]}, dict(legacy, **{'learned.weight': torch.ones(3, 2)})]:
    try:
        migrate_seed_state(expected, bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid checkpoint was accepted')
'''
    result = subprocess.run([str(root / 'venv/bin/python'), '-c', code],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
