"""Acquire only reviewed Seed PoC artifacts, with bounded size and content hashes.

No model code is loaded here. The caller must have obtained the user's consent
for the exact manifest; the CLI flag records that decision, not a UI preference.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'docs/voice-stack/seed-vc-poc-artifacts.json'


def _require(condition):
    if not condition:
        raise ValueError('artifact_manifest_invalid')


def validate_manifest(manifest):
    try:
        files = manifest['files']
        _require(isinstance(files, list) and files)
        _require(type(manifest['total_bytes']) is int)
        seen, total = set(), 0
        for item in files:
            repo, revision, name = item['repo'], item['revision'], item['rfilename']
            _require(isinstance(repo, str) and re.fullmatch(r'[\w.-]+/[\w.-]+', repo, re.ASCII))
            _require(all(p not in ('.', '..') for p in repo.split('/')))
            _require(isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision))
            _require(isinstance(name, str) and name and '\\' not in name and '\0' not in name)
            _require(not PurePosixPath(name).is_absolute())
            _require(all(p not in ('', '.', '..') for p in name.split('/')))
            _require(type(item['size']) is int and item['size'] > 0)
            _require(re.fullmatch('[0-9a-f]{40}', item['blobId']))
            if 'lfs' in item:
                _require(re.fullmatch('[0-9a-f]{64}', item['lfs']['sha256']))
                _require(type(item['lfs']['size']) is int and item['lfs']['size'] == item['size'])
            key = (repo, revision, name)
            _require(key not in seen)
            seen.add(key)
            total += item['size']
        _require(total == manifest['total_bytes'])
    except (AssertionError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('artifact_manifest_invalid') from exc
    return files


def artifact_path(root, item):
    root = Path(root).resolve()
    target = root / item['repo'] / item['revision'] / item['rfilename']
    if not target.resolve().is_relative_to(root):
        raise ValueError('artifact_path_escape')
    return target


def verify_file(path, item):
    digest = hashlib.sha256()
    blob = hashlib.sha1(f"blob {item['size']}\0".encode())
    size = 0
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > item['size']:
                raise ValueError('artifact_size_mismatch')
            digest.update(chunk)
            blob.update(chunk)
    if size != item['size']:
        raise ValueError('artifact_size_mismatch')
    if ('lfs' in item and digest.hexdigest() != item['lfs']['sha256']
            or 'lfs' not in item and blob.hexdigest() != item['blobId']):
        raise ValueError('artifact_hash_mismatch')
    return {'path': str(Path(path).resolve()), 'size': size, 'sha256': digest.hexdigest()}


def fetch_artifacts(manifest, root, *, opener=urlopen, progress=None):
    files = validate_manifest(manifest)
    # Validate all destinations before the first network operation.
    targets = [artifact_path(root, item) for item in files]
    verified = []
    for item, target in zip(files, targets):
        url = f"https://huggingface.co/{item['repo']}/resolve/{item['revision']}/{quote(item['rfilename'], safe='/')}?download=true"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.part', delete=False) as out:
                    temporary = Path(out.name)
                    size = 0
                    with opener(url, timeout=30) as response:
                        while chunk := response.read(1024 * 1024):
                            size += len(chunk)
                            if size > item['size']:
                                raise ValueError('artifact_size_mismatch')
                            out.write(chunk)
                verify_file(temporary, item)
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        record = {**verify_file(target, item), 'repo': item['repo'], 'revision': item['revision'],
                  'rfilename': item['rfilename'], 'url': url}
        verified.append(record)
        if progress:
            progress(record)
    return {'status': 'verified', 'verified_bytes': sum(x['size'] for x in verified), 'files': verified}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--consent-reviewed', action='store_true', required=True,
                        help='Confirm consent for the committed fixed manifest was obtained')
    args = parser.parse_args(argv)
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    result = fetch_artifacts(manifest, args.output, progress=lambda item: print(json.dumps(
        {'verified': item['repo'] + '/' + item['rfilename'], 'bytes': item['size']}, ensure_ascii=False), flush=True))
    (args.output / 'verified-artifacts.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'files': len(result['files']), 'bytes': result['verified_bytes']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
