"""Inspect and archive a Linux onedir installation, preserving internal file links."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import subprocess
import tarfile
import tempfile

try:
    from .check_voice_distribution import _check_name, _zip, check
    from .distribution_policy import ARCHIVE_SUFFIXES, OCR_RUNTIME_DATA
except ImportError:
    from check_voice_distribution import _check_name, _zip, check
    from distribution_policy import ARCHIVE_SUFFIXES, OCR_RUNTIME_DATA

RUNTIME = ('vrct-vox', 'vrct-vox-sidecar', '_internal/base_library.zip',
           '_internal/build/vrct-voice-gate', '_internal/build/vrct-source-bridge',
           '_internal/build/vrct-vc-worker', '_internal/build/vrct-asr-capture',
           '_internal/build/speechcpp/speech', '_internal/build/speechcpp/bundle.json',
           '_internal/integrations/rvc/live_worker.py',
           '_internal/integrations/seed_vc/live_worker.py',
           '_internal/licenses/VRCT/LICENSE', '_internal/licenses/VRCT/NOTICE.md',
           *('_internal/' + name for name in OCR_RUNTIME_DATA))


def check_tree(root, *, require_runtime=False, allow_directory_links=False):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f'Expected a real installation directory: {root}')
    root = root.resolve()
    for path in root.rglob('*'):
        _check_name(path.relative_to(root).as_posix(), root)
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            try:
                target = path.resolve(strict=True)
                valid = (not Path(os.readlink(path)).is_absolute() and target.is_relative_to(root)
                         and (target.is_file() or (allow_directory_links and target.is_dir())))
            except (OSError, RuntimeError):
                valid = False
            if not valid:
                raise ValueError(f'Unsafe distribution symlink: {path}')
        elif stat.S_ISREG(mode):
            check([path])
        elif not stat.S_ISDIR(mode):
            raise ValueError(f'Special file in distribution: {path}')
    if require_runtime:
        for name in RUNTIME:
            path = root / name
            if not path.is_file():
                raise ValueError(f'Missing runtime component: {name}')
            if name in ('vrct-vox', 'vrct-vox-sidecar') or name.startswith('_internal/build/vrct-') or name.endswith('/speech'):
                with path.open('rb') as src:
                    header = src.read(20)
                if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00' or not os.access(path, os.X_OK):
                    raise ValueError(f'Expected executable x86_64 ELF runtime: {name}')


def inspect_tar(path):
    """Inventory before extraction. No devices, hardlinks, ambiguous paths or outside links."""
    try:
        with tarfile.open(path, 'r:gz') as archive:
            members = {}
            roots = set()
            for member in archive:
                name = member.name
                parts = PurePosixPath(name).parts
                if not parts or name.startswith('/') or '\\' in name or '..' in parts or name != '/'.join(parts) or name in members:
                    raise ValueError(f'Unsafe/duplicate archive path: {name}')
                _check_name(name, path)
                roots.add(parts[0])
                members[name] = member
                if not (member.isfile() or member.isdir() or member.issym()) or member.mode & 0o6000:
                    raise ValueError(f'Unsafe archive type/mode: {name}')
                if member.isfile():
                    with archive.extractfile(member) as src:
                        magic = src.read(4)
                    if name.lower().endswith('.zip') or magic.startswith(b'PK\x03\x04'):
                        if member.size > 128 * 1024 * 1024:
                            raise ValueError(f'Oversized nested archive: {name}')
                        with archive.extractfile(member) as src, tempfile.TemporaryFile() as snapshot:
                            import shutil
                            shutil.copyfileobj(src, snapshot)
                            snapshot.seek(0)
                            _zip(snapshot, f'{path}!{name}')
                    elif name.lower().endswith(ARCHIVE_SUFFIXES):
                        raise ValueError(f'Unsupported nested archive: {name}')
            if len(roots) != 1:
                raise ValueError('Expected one archive root')
            root = next(iter(roots))
            for name, member in members.items():
                for parent in PurePosixPath(name).parents:
                    if str(parent) in members and not members[str(parent)].isdir():
                        raise ValueError(f'Non-directory archive parent: {name}')
                seen = set()
                while member.issym():
                    if member.name in seen or member.linkname.startswith('/') or '\\' in member.linkname:
                        raise ValueError(f'Unsafe archive link: {name}')
                    seen.add(member.name)
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
                    if not target.startswith(root + '/') or target not in members:
                        raise ValueError(f'Outside/broken archive link: {name}')
                    member = members[target]
                if seen and not member.isfile():
                    raise ValueError(f'Link must resolve to a regular file: {name}')
            return len(members)
    except (tarfile.TarError, OSError) as exc:
        raise ValueError(f'Cannot inspect archive: {path}') from exc


def sha256(path):
    with Path(path).open('rb') as src:
        return hashlib.file_digest(src, 'sha256').hexdigest()


def normalize_modes(root):
    """An archive installed by root must remain readable/executable by normal users."""
    for path in [Path(root), *Path(root).rglob('*')]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)


def inventory(root):
    rows = []
    for path in sorted(Path(root).rglob('*')):
        row = {'path': path.relative_to(root).as_posix()}
        if path.is_symlink():
            row['link'] = os.readlink(path)
        elif path.is_file():
            row.update(size=path.stat().st_size, sha256=sha256(path), mode=oct(path.stat().st_mode & 0o777))
            with path.open('rb') as src:
                elf = src.read(4) == b'\x7fELF'
            if elf:
                result = subprocess.run(['readelf', '--version-info', str(path)], check=True, capture_output=True, text=True)
                row['elf_versions'] = sorted(set(re.findall(r'\b(?:GLIBC|GLIBCXX|CXXABI)_[0-9.]+', result.stdout)))
        else:
            continue
        rows.append(row)
    return rows


def pack(root, destination, *, require_runtime=True):
    root, destination = Path(root), Path(destination)
    check_tree(root, require_runtime=require_runtime)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve().is_relative_to(root.resolve()):
        raise ValueError('Archive must be outside its source tree')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.part', delete=False) as src:
            temporary = Path(src.name)
        with tarfile.open(temporary, 'w:gz', dereference=False, compresslevel=3) as archive:
            archive.add(root, arcname=root.name)
        inspect_tar(temporary)
        os.replace(temporary, destination)
        checksum = destination.with_name(destination.name + '.sha256')
        checksum.write_text(f'{sha256(destination)}  {destination.name}\n')
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        pack(args.path, args.output)
    elif args.path.is_dir():
        check_tree(args.path, require_runtime=True)
    else:
        print(json.dumps({'entries': inspect_tar(args.path), 'sha256': sha256(args.path)}))


if __name__ == '__main__':
    main()
