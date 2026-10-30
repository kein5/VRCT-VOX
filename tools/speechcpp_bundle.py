"""Stage a pinned speech.cpp binary and notices; never acquire models.

Build-time only. A local archive is the default explicit source; --download is
opt-in. The application never invokes this downloader during normal startup.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT/'docs/voice-stack/speechcpp-bundle-artifacts.json'
NOTICES = ROOT/'licenses/speech.cpp'
VERSION = '0.9.0'
COMMIT = '49f022a48bc1c7e797aa64dd08d2d9655baf299e'
VARIANTS = ('linux-x64-cpu', 'linux-x64-vulkan')
NOTICE_NAMES = frozenset(('NOTICE.md', 'speech.cpp-LICENSE', 'ggml-LICENSE',
    'cpp-httplib-LICENSE', 'miniaudio-LICENSE', 'GCC-COPYING3', 'GCC-COPYING.RUNTIME'))
INVENTORY = frozenset({'speech', *('notices/'+name for name in NOTICE_NAMES)})


def _require(condition, code='manifest'):
    if not condition:
        raise ValueError('speech_bundle_'+code)


def _identity(value):
    _require(type(value['size']) is int and 0 < value['size'] <= 128*1024*1024)
    _require(isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']))


def _asset(value):
    try:
        _require(value['id'] in VARIANTS)
        name = f"speech-{VERSION}-{value['id']}.zip"
        _require(value['name'] == name)
        _require(value['url'] == f'https://github.com/nyosegawa/speech.cpp/releases/download/v{VERSION}/{name}')
        _identity(value)
    except (KeyError, TypeError, AttributeError):
        raise ValueError('speech_bundle_manifest') from None
    return value


def load_manifest(path=DEFAULT_MANIFEST):
    try:
        value = json.loads(Path(path).read_text())
        _require(type(value['schema']) is int and value['schema'] == 1)
        _require(value['component'] == 'speech.cpp' and value['version'] == VERSION)
        _require(value['source_commit'] == COMMIT)
        _require(set(value['assets']) == set(VARIANTS))
        for key, asset in value['assets'].items():
            _asset(asset)
            _require(key == asset['id'])
        _require(len(value['notices']) == len(NOTICE_NAMES))
        _require({row['path'] for row in value['notices']} == NOTICE_NAMES)
        for row in value['notices']:
            _identity(row)
        return value
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError('speech_bundle_manifest') from None


def _record(path, expected=None):
    path = Path(path)
    try:
        _require(stat.S_ISREG(path.lstat().st_mode), 'file')
        digest, size = hashlib.sha256(), 0
        with path.open('rb') as src:
            while block := src.read(1024*1024):
                size += len(block)
                if expected:
                    _require(size <= expected['size'], 'size')
                digest.update(block)
        result = dict(size=size, sha256=digest.hexdigest())
        if expected:
            _require(size == expected['size'], 'size')
            _require(result['sha256'] == expected['sha256'], 'hash')
        return result
    except OSError:
        raise ValueError('speech_bundle_file') from None


def fetch_archive(asset, destination, *, opener=urlopen):
    _asset(asset)
    destination = Path(destination)
    _require(not os.path.lexists(destination), 'destination_exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.part', delete=False) as out:
            temporary = Path(out.name)
            total, deadline = 0, time.monotonic()+180
            with opener(asset['url'], timeout=30) as response:
                while block := response.read(1024*1024):
                    total += len(block)
                    _require(total <= asset['size'], 'size')
                    _require(time.monotonic() <= deadline, 'download_timeout')
                    out.write(block)
        _record(temporary, asset)
        # Same-filesystem hard link publishes without replacing a file or link
        # created by another invocation after the initial existence check.
        os.link(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _verified_archive(path, asset):
    # Hash the exact private snapshot subsequently read by ZipFile. Reopening
    # the caller's pathname after hashing would allow a replaced archive to
    # contribute bytes that were never verified.
    with tempfile.TemporaryFile() as snapshot:
        digest, size = hashlib.sha256(), 0
        _require(stat.S_ISREG(path.lstat().st_mode), 'file')
        with path.open('rb') as src:
            while block := src.read(1024*1024):
                size += len(block)
                _require(size <= asset['size'], 'size')
                digest.update(block)
                snapshot.write(block)
        _require(size == asset['size'], 'size')
        _require(digest.hexdigest() == asset['sha256'], 'hash')
        snapshot.seek(0)
        with zipfile.ZipFile(snapshot) as archive:
            yield archive


def stage_bundle(archive, output, asset, *, notice_root=NOTICES):
    _asset(asset)
    manifest = load_manifest()
    output, archive, notice_root = Path(output), Path(archive), Path(notice_root)
    _require(not os.path.lexists(output), 'destination_exists')
    for row in manifest['notices']:
        _record(notice_root/row['path'], row)
    created = False
    try:
        with _verified_archive(archive, asset) as source:
            entries = [entry for entry in source.infolist() if entry.filename == 'speech']
            _require(len(entries) == 1, 'executable')
            entry = entries[0]
            mode = stat.S_IFMT(entry.external_attr >> 16)
            _require(not entry.is_dir() and mode in (0, stat.S_IFREG)
                     and 0 < entry.file_size <= 128*1024*1024, 'executable')
            output.mkdir(parents=True, exist_ok=False)
            created = True
            executable = output/'speech'
            with source.open(entry) as src, executable.open('xb') as out:
                shutil.copyfileobj(src, out, length=1024*1024)
            executable.chmod(0o755)
        (output/'notices').mkdir()
        for row in manifest['notices']:
            target = output/'notices'/row['path']
            with (notice_root/row['path']).open('rb') as src, target.open('xb') as out:
                shutil.copyfileobj(src, out)
            _record(target, row)
        result = dict(schema=1, component='speech.cpp', version=VERSION, source_commit=COMMIT,
            variant=asset['id'], archive={k: asset[k] for k in ('name', 'size', 'sha256', 'url')},
            files=[dict(path=name, **_record(output/name)) for name in sorted(INVENTORY)])
        with (output/'bundle.json').open('x') as out:
            json.dump(result, out, indent=2)
            out.write('\n')
        verify_bundle(output)
        return result
    except BaseException:
        if created:
            shutil.rmtree(output)
        raise


def verify_bundle(root):
    root = Path(root)
    _require(root.is_dir() and not root.is_symlink(), 'inventory')
    entries = list(root.rglob('*'))
    _require(all(not p.is_symlink() for p in entries), 'inventory')
    _require({p.relative_to(root).as_posix() for p in entries if not p.is_dir()}
             == INVENTORY | {'bundle.json'}, 'inventory')
    _require(stat.S_ISREG((root/'bundle.json').lstat().st_mode), 'inventory')
    _require((root/'bundle.json').stat().st_size <= 64*1024, 'inventory')
    try:
        value = json.loads((root/'bundle.json').read_text())
        _require(type(value['schema']) is int and value['schema'] == 1, 'inventory')
        _require(value['component'] == 'speech.cpp' and value['version'] == VERSION
                 and value['source_commit'] == COMMIT, 'inventory')
        _asset(dict(value['archive'], id=value['variant']))
        _require(len(value['files']) == len(INVENTORY), 'inventory')
        _require({row['path'] for row in value['files']} == INVENTORY, 'inventory')
        for row in value['files']:
            _identity(row)
            _record(root/row['path'], row)
        for row in load_manifest()['notices']:
            _record(root/'notices'/row['path'], row)
        _require(bool((root/'speech').stat().st_mode & 0o111), 'executable')
        return value
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError('speech_bundle_inventory') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=VARIANTS, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--archive', type=Path)
    source.add_argument('--download', action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        _require(not os.path.lexists(args.output), 'destination_exists')
        asset = load_manifest()['assets'][args.variant]
        if args.archive:
            result = stage_bundle(args.archive, args.output, asset)
        else:
            with tempfile.TemporaryDirectory(prefix='vrct-speech-download-') as temporary:
                archive = fetch_archive(asset, Path(temporary)/asset['name'])
                result = stage_bundle(archive, args.output, asset)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, zipfile.BadZipFile):
        parser.exit(1, 'speech_bundle_failed: verify the archive, notices and output directory\n')


if __name__ == '__main__':
    main()
