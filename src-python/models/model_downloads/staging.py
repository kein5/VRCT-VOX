"""One owner per download root, including across processes and interrupted runs."""
import json
import os
import re
import stat
import sys


class RootLease:
    def __init__(self, root):
        self.path = root / '.download.lock'
        self.fd = None

    def acquire(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('unsafe_destination')
            if sys.platform == 'win32':
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'\0'); os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if error.errno in (11, 13, 35):
                raise ValueError('download_busy') from None
            raise
        except Exception:
            os.close(fd); raise
        self.fd = fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd); self.fd = None


def mark_owned(path, entry):
    data = dict(product='VRCT-TTS-model-download-v1', id=entry.id, revision=entry.revision,
                files=[a.filename for a in entry.artifacts], directory=path.name)
    with (path / 'owner.json').open('x') as out:
        json.dump(data, out); out.flush(); os.fsync(out.fileno())


def recover_owned(root, entries):
    """Caller holds RootLease. Never follow links or remove unrecognized content."""
    for path in root.glob('.partial-*'):
        if not re.fullmatch(r'\.partial-[0-9a-f]{32}', path.name) or not stat.S_ISDIR(path.lstat().st_mode):
            continue
        marker = path / 'owner.json'
        try:
            if not stat.S_ISREG(marker.lstat().st_mode) or marker.stat().st_size > 4096:
                continue
            data = json.loads(marker.read_text())
            entry = entries.get(data.get('id'))
            if (entry is None or data != dict(product='VRCT-TTS-model-download-v1', id=entry.id,
                    revision=entry.revision, files=[a.filename for a in entry.artifacts], directory=path.name)):
                continue
            children = list(path.iterdir())
            allowed = {'owner.json', 'receipt.json', *(a.filename for a in entry.artifacts)}
            if any(p.name not in allowed or not stat.S_ISREG(p.lstat().st_mode) for p in children):
                continue
            for child in children: child.unlink()
            path.rmdir()
        except (FileNotFoundError, ValueError, TypeError, AttributeError):
            # Unknown/incomplete journals are not evidence that we own user files.
            continue
