"""Consent-bound files are published only after content identity is verified."""
import hashlib
import importlib
import io
import json
from pathlib import Path

import pytest


def module():
    return importlib.import_module('tools.seedvc_artifacts')


def manifest(*, lfs=True):
    item = {'repo': 'owner/model', 'revision': 'a' * 40, 'rfilename': 'model.bin', 'size': 4,
            'blobId': hashlib.sha1(b'blob 4\0data').hexdigest()}
    if lfs:
        item['lfs'] = {'sha256': hashlib.sha256(b'data').hexdigest(), 'size': 4}
    return {'files': [item], 'total_bytes': 4}


def fetch(data, calls):
    def open_url(url, timeout):
        calls.append(url)
        return io.BytesIO(data)
    return open_url


@pytest.mark.parametrize('lfs', [True, False])
def test_exact_manifest_files_verified_and_existing_files_reused(tmp_path, lfs):
    calls = []
    result = module().fetch_artifacts(manifest(lfs=lfs), tmp_path, opener=fetch(b'data', calls))
    assert calls == ['https://huggingface.co/owner/model/resolve/' + 'a' * 40 + '/model.bin?download=true']
    assert result['verified_bytes'] == 4 and result['files'][0]['sha256'] == hashlib.sha256(b'data').hexdigest()
    assert Path(result['files'][0]['path']).read_bytes() == b'data'
    assert module().fetch_artifacts(manifest(lfs=lfs), tmp_path, opener=fetch(b'bad', calls))['verified_bytes'] == 4
    assert len(calls) == 1
    assert len(list(tmp_path.rglob('*.bin'))) == 1


@pytest.mark.parametrize('body', [b'bad!', b'dat', b'data plus unexpected bytes'])
def test_bad_or_partial_content_never_promoted(tmp_path, body):
    with pytest.raises(ValueError, match='artifact_(size|hash)_mismatch'):
        module().fetch_artifacts(manifest(), tmp_path, opener=fetch(body, []))
    assert not list(tmp_path.rglob('*.bin'))
    assert not list(tmp_path.rglob('*.part'))


def test_interrupted_read_leaves_no_checkpoint(tmp_path):
    class Broken(io.BytesIO):
        def read(self, size):
            raise OSError('injected interruption')
    with pytest.raises(OSError):
        module().fetch_artifacts(manifest(), tmp_path, opener=lambda *a, **k: Broken())
    assert not [p for p in tmp_path.rglob('*') if p.is_file()]


def test_existing_corruption_is_not_silently_used_or_overwritten(tmp_path):
    m, calls = module(), []
    result = m.fetch_artifacts(manifest(), tmp_path, opener=fetch(b'data', calls))
    target = Path(result['files'][0]['path'])
    target.write_bytes(b'evil')
    with pytest.raises(ValueError, match='artifact_hash_mismatch'):
        m.fetch_artifacts(manifest(), tmp_path, opener=fetch(b'data', calls))
    assert target.read_bytes() == b'evil' and len(calls) == 1


@pytest.mark.parametrize('key,value', [('repo', '../model'), ('repo', 'owner/..'), ('revision', 'main'),
    ('rfilename', '../escape'), ('rfilename', '/tmp/escape'), ('rfilename', 'a\\b'),
    ('size', True), ('size', 0), ('blobId', 'invalid')])
def test_invalid_manifest_rejected_before_any_acquisition(tmp_path, key, value):
    data, calls = manifest(lfs=False), []
    data['files'][0][key] = value
    with pytest.raises(ValueError, match='artifact_manifest_invalid'):
        module().fetch_artifacts(data, tmp_path, opener=fetch(b'data', calls))
    assert not calls


@pytest.mark.parametrize('fault', ['total', 'duplicate', 'bad_lfs_hash', 'lfs_size'])
def test_entire_manifest_validated_before_first_request(tmp_path, fault):
    data, calls = manifest(), []
    if fault == 'total':
        data['total_bytes'] = 5
    elif fault == 'duplicate':
        data['files'] *= 2
        data['total_bytes'] *= 2
    elif fault == 'bad_lfs_hash':
        data['files'][0]['lfs']['sha256'] = 'not a digest'
    else:
        data['files'][0]['lfs']['size'] = 5
    with pytest.raises(ValueError, match='artifact_manifest_invalid'):
        module().fetch_artifacts(data, tmp_path, opener=fetch(b'data', calls))
    assert not calls


def test_symlink_escape_is_rejected_before_acquisition(tmp_path):
    root, elsewhere = tmp_path / 'root', tmp_path / 'elsewhere'
    root.mkdir()
    elsewhere.mkdir()
    (root / 'owner').symlink_to(elsewhere, target_is_directory=True)
    calls = []
    with pytest.raises(ValueError, match='artifact_path_escape'):
        module().fetch_artifacts(manifest(), root, opener=fetch(b'data', calls))
    assert not calls and not list(elsewhere.iterdir())


def test_cli_requires_explicit_consent_flag(tmp_path):
    with pytest.raises(SystemExit) as exc:
        module().main(['--output', str(tmp_path)])
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


def test_committed_manifest_keeps_approved_total_and_only_five_models():
    root = Path(__file__).parents[2]
    data = json.loads((root / 'docs/voice-stack/seed-vc-poc-artifacts.json').read_text())
    module().validate_manifest(data)
    assert len(data['files']) == 12 and data['total_bytes'] == 1523519558
    assert len({x['repo'] for x in data['files']}) == 5
    assert not any(x['rfilename'].endswith(('.wav', '.mp3', '.jpg')) for x in data['files'])


def test_validation_remains_enabled_under_optimized_python():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-O', '-c', '''
from tools.seedvc_artifacts import validate_manifest
try:
    validate_manifest({'files': [], 'total_bytes': 0})
except ValueError:
    raise SystemExit(0)
raise SystemExit(1)
'''], cwd=Path(__file__).parents[2], capture_output=True)
    assert result.returncode == 0, result.stderr
