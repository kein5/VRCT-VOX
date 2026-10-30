# SPDX-License-Identifier: GPL-3.0-only
"""Validate consented local inputs before importing the optional VC runtime."""
import hashlib
from pathlib import Path
import wave

from tools.seedvc_artifacts import artifact_path, validate_manifest, verify_file


class OfflineAssets:
    def __init__(self, manifest, root):
        self._files = {}
        for item in validate_manifest(manifest):
            key = (item['repo'], item['rfilename'])
            if key in self._files:
                raise ValueError('ambiguous_artifact')
            path = artifact_path(root, item)
            verify_file(path, item)
            self._files[key] = path

    def file(self, repo, name):
        try:
            return self._files[(repo, name)]
        except KeyError as exc:
            raise ValueError('unapproved_artifact') from exc


def validate_reference(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError('reference_local_file')
    with wave.open(str(path), 'rb') as source:
        rate = source.getframerate()
        duration = source.getnframes() / rate
        if not 1 <= duration <= 30:
            raise ValueError('reference_duration')
        result = {'duration_s': duration, 'sample_rate': rate,
                  'channels': source.getnchannels(), 'sample_width': source.getsampwidth()}
    with path.open('rb') as source:
        result['sha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
    return result


def require_complete_state(expected, supplied):
    missing = sorted(set(expected) - set(supplied))
    mismatched = sorted(key for key in expected.keys() & supplied.keys()
                        if expected[key].shape != supplied[key].shape)
    if missing or mismatched:
        raise ValueError(f'checkpoint_incomplete: missing={missing}, shapes={mismatched}')
    return {'required': len(expected), 'unused': len(supplied.keys() - expected.keys())}
