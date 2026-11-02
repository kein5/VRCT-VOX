"""Reject Python lock entries that cannot be verified during installation."""
import argparse
from pathlib import Path
import re
import tomllib
from urllib.parse import parse_qs, urlsplit


def validate_lock(path):
    """Require SHA-256 for every archive and full, immutable Git revisions."""
    with Path(path).open('rb') as stream:
        lock = tomllib.load(stream)
    if not lock.get('package'):
        raise ValueError(f'{path}: no locked packages')
    for package in lock['package']:
        label = f"{path}: {package['name']} {package['version']}"
        source = package['source']
        # This application is not installed. No other local sources are exempt.
        if package['name'] == 'vrct-vox' and source == {'virtual': '.'}:
            continue
        if set(source) == {'git'}:
            url = urlsplit(source['git'])
            revision = parse_qs(url.query)
            if (not re.fullmatch(r'[0-9a-fA-F]{40}', url.fragment)
                    or revision.get('rev') != [url.fragment]
                    or 'branch' in revision or 'tag' in revision):
                raise ValueError(f'{label}: Git dependency must be pinned to a full 40-character commit SHA (rev and fragment)')
            continue
        if set(source) not in ({'registry'}, {'url'}):
            raise ValueError(f'{label}: unsupported non-VCS source without verifiable archive hashes: {source}')
        artifacts = package.get('wheels', []) + ([package['sdist']] if 'sdist' in package else [])
        if not artifacts:
            raise ValueError(f'{label}: non-VCS package has no hashed archives')
        for artifact in artifacts:
            if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', artifact.get('hash', '')):
                raise ValueError(f"{label}: missing or invalid SHA-256 for {artifact.get('url', 'archive')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lock', type=Path, nargs='?', default=Path(__file__).resolve().parents[1] / 'uv.lock')
    args = parser.parse_args()
    try:
        validate_lock(args.lock)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Python dependency verification failed: {exc}\n')


if __name__ == '__main__':
    main()
