"""Pinned admission and owned, cancellable transactions for built-in weights.

Consent remains at the controller boundary. This module never acquires files
while checking availability. Existing, unverified directories are preserved.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from threading import Event, RLock, Thread, Timer
import time
from types import SimpleNamespace
from uuid import uuid4

from models.model_downloads.manager import Cancelled, directory
from models.model_downloads.staging import RootLease, mark_owned, recover_owned
from models.model_downloads.transport import open_public
from models.model_downloads.verification import CHUNK, verify_file

ARTIFACT_TIMEOUT = 1800
READ_TIMEOUT = 60
MARKER = '.weight_verified.json'
_verification_lock = RLock()


def manifest_identity(repo, pin):
    return hashlib.sha256(json.dumps(
        dict(repo=repo, **pin), sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def _artifacts(pin):
    artifacts = []
    for name, (size, digest) in pin['files'].items():
        # Built-in manifests currently contain only flat file sets.
        if Path(name).name != name or name in ('.', '..') or '/' in name or '\\' in name:
            raise ValueError('unsafe_destination')
        artifacts.append(SimpleNamespace(filename=name, size=size, sha256=digest))
    if not artifacts:
        raise ValueError('empty_manifest')
    return artifacts


def _stats(path, artifacts):
    # Check ancestors without creating anything during an availability query.
    for parent in (path, *path.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('unsafe_destination')
    result = {}
    for artifact in artifacts:
        info = (path / artifact.filename).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != artifact.size:
            raise ValueError('size_mismatch')
        result[artifact.filename] = [info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                                     info.st_dev, info.st_ino]
    return result


def _receipt(path, identity, stats):
    temporary = path / ('.verified-' + uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(dict(schema=2, manifest=identity, files=stats), stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path / MARKER)
    finally:
        temporary.unlink(missing_ok=True)


def verified_directory(path, repo, pin, control=None):
    """Hash once per manifest and unchanged file identities, never by load success."""
    path = Path(path).absolute()
    checkpoint = control.checkpoint if control is not None else lambda: None
    # Concurrent startup/load queries must not hash the same large files twice.
    with _verification_lock:
        checkpoint()
        try:
            artifacts = _artifacts(pin)
            identity = manifest_identity(repo, pin)
            before = _stats(path, artifacts)
            marker = path / MARKER
            try:
                if stat.S_ISREG(marker.lstat().st_mode) and marker.stat().st_size < 65536:
                    receipt = json.loads(marker.read_text(encoding='utf-8'))
                    if receipt == dict(schema=2, manifest=identity, files=before):
                        return True
            except (OSError, ValueError):
                pass
            for artifact in artifacts:
                checkpoint()
                verify_file(path / artifact.filename, artifact, checkpoint)
            checkpoint()
            if before != _stats(path, artifacts):
                return False
            try:
                _receipt(path, identity, before)
            except OSError:
                # Read-only existing installations can still be verified.
                pass
            return True
        except (OSError, ValueError):
            return False


class DownloadControl:
    """Own the cancellation event and interruptible HTTP body of one attempt."""
    def __init__(self, closing=None):
        self.event, self.lock = Event(), RLock()
        self.closing = closing or Event()
        self.response = None
        self.deadline = None
        self.expired = False

    def checkpoint(self):
        if self.event.is_set() or self.closing.is_set():
            raise Cancelled()
        if self.expired or (self.deadline is not None and time.monotonic() >= self.deadline):
            raise TimeoutError('download_deadline')

    def _abort(self):
        if self.response is not None and hasattr(self.response, 'abort'):
            self.response.abort()

    def cancel(self, timeout=2):
        self.event.set()
        if not self.lock.acquire(timeout=max(0, timeout)):
            return False
        try:
            self._abort()
            return True
        finally:
            self.lock.release()

    def _expire(self):
        with self.lock:
            self.expired = True
            self._abort()

    @contextmanager
    def artifact(self, timeout):
        self.deadline = time.monotonic() + timeout
        self.expired = False
        timer = Timer(timeout, self._expire)
        timer.daemon = True
        timer.start()
        try:
            self.checkpoint()
            yield
            self.checkpoint()
        finally:
            timer.cancel()
            timer.join()
            self.deadline = None

    @contextmanager
    def body(self, response):
        with self.lock:
            self.response = response
        try:
            self.checkpoint()
            yield response
        finally:
            with self.lock:
                self.response = None


def _transport(url):
    # Keep the legacy 60-second read timeout. The timer also bounds slow trickles.
    return open_public(url, timeout=READ_TIMEOUT)


def stream_artifact(url, path, artifact, control, callback=None, *,
                    transport=_transport, timeout=ARTIFACT_TIMEOUT):
    """Write only to a caller-owned private staging path; never publish here."""
    with control.artifact(timeout):
        for attempt in range(3):
            try:
                control.checkpoint()
                with transport(url) as response, control.body(response), path.open('xb') as output:
                    digest, received = hashlib.sha256(), 0
                    while True:
                        control.checkpoint()
                        block = response.read(min(CHUNK, artifact.size - received + 1))
                        control.checkpoint()
                        if not block:
                            break
                        if received + len(block) > artifact.size:
                            raise ValueError('size_mismatch')
                        output.write(block)
                        digest.update(block)
                        received += len(block)
                        if callback is not None:
                            callback(received / artifact.size)
                    output.flush()
                    os.fsync(output.fileno())
                if received != artifact.size:
                    raise ValueError('size_mismatch')
                if digest.hexdigest() != artifact.sha256:
                    raise ValueError('hash_mismatch')
                return
            except OSError as error:
                path.unlink(missing_ok=True)
                control.checkpoint()
                status = getattr(error, 'code', None)
                if (attempt == 2 or (status is not None and 400 <= status < 500 and status != 429)
                        or getattr(error, 'errno', None) is not None):
                    raise
                control.event.wait(2 * (attempt + 1))
                control.checkpoint()


def download_directory(root, name, repo, pin, control=None, callback=None, *,
                       transport=_transport, timeout=ARTIFACT_TIMEOUT):
    """Publish a complete verified bundle under the catalog's OS root lease."""
    control = control or DownloadControl()
    root = Path(root).absolute()
    if Path(name).name != name:
        raise ValueError('unsafe_destination')
    artifacts = _artifacts(pin)
    entry = SimpleNamespace(id=name, revision=manifest_identity(repo, pin), artifacts=artifacts)
    lease, staging, preserved = RootLease(root), None, None
    final = root / name
    try:
        control.checkpoint()
        directory(root)
        lease.acquire()
        recover_owned(root, {name: entry}, extra_files=(MARKER,))
        if verified_directory(final, repo, pin, control):
            return True
        if shutil.disk_usage(root).free < sum(a.size for a in artifacts) + 64 * 1024 * 1024:
            raise ValueError('insufficient_space')
        staging = root / ('.partial-' + uuid4().hex)
        staging.mkdir(mode=0o700)
        mark_owned(staging, entry)
        for artifact in artifacts:
            stream_artifact(
                f'https://huggingface.co/{repo}/resolve/{pin["revision"]}/{artifact.filename}',
                staging / artifact.filename, artifact, control,
                callback if artifact.filename == 'model.bin' else None,
                transport=transport, timeout=timeout,
            )
        if not verified_directory(staging, repo, pin, control):
            raise ValueError('verification_failed')
        # The same linearization point as catalog publication: cancellation
        # before this lock prevents publication; cancellation afterward is too late.
        with control.lock:
            control.checkpoint()
            if final.exists() or final.is_symlink():
                if not stat.S_ISDIR(final.lstat().st_mode):
                    raise ValueError('unsafe_destination')
                preserved = root / ('.preserved-' + name + '-' + uuid4().hex)
                final.rename(preserved)
            try:
                staging.rename(final)
                staging = None
            except BaseException:
                if preserved is not None:
                    preserved.rename(final)
                raise
        return True
    finally:
        try:
            if staging is not None:
                shutil.rmtree(staging)
        finally:
            lease.close()


class LegacyDownloads:
    """Controller-owned workers. Busy/closed requests never start another worker."""
    def __init__(self):
        self.lock, self.closed, self.jobs = RLock(), False, {}
        self.closing = Event()
        self._controls = ()

    def start(self, key, operation, terminal, *, job_id=None):
        with self.lock:
            if self.closed or self.closing.is_set():
                raise ValueError('downloads_closed')
            previous = self.jobs.get(key)
            if previous is not None and previous[1].is_alive():
                raise ValueError('download_busy')
            control = DownloadControl(self.closing)
            control.job_id = job_id

            def run():
                error = None
                ready = False
                try:
                    control.checkpoint()
                    ready = operation(control) is True
                    control.checkpoint()
                    if not ready:
                        error = 'verification_failed'
                except Cancelled:
                    ready = False
                    error = 'cancelled'
                except Exception as exc:
                    ready = False
                    error = str(exc) if str(exc) in {
                        'download_busy', 'download_deadline', 'size_mismatch', 'hash_mismatch',
                        'insufficient_space', 'unsafe_destination',
                    } else 'download_failed'
                finally:
                    terminal(ready, error)

            thread = Thread(target=run, name='legacy-model-download', daemon=True)
            self.jobs[key] = control, thread
            self._controls = tuple(job[0] for job in self.jobs.values())
            thread.start()
            return thread

    def active_job(self, key):
        with self.lock:
            job = self.jobs.get(key)
            return job[0].job_id if job is not None and job[1].is_alive() else None

    def stop(self, key, timeout=2):
        deadline = time.monotonic() + max(0, timeout)
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            return False
        try:
            job = self.jobs.get(key)
            if job is None:
                return True
            control, thread = job
        finally:
            self.lock.release()
        control.cancel(timeout=max(0, deadline - time.monotonic()))
        thread.join(max(0, deadline - time.monotonic()))
        return not thread.is_alive()

    def wait(self, key, timeout=1800):
        with self.lock:
            job = self.jobs.get(key)
        if job is None:
            return True
        job[1].join(timeout)
        return not job[1].is_alive() or self.stop(key)

    def request_close(self):
        """Signal every attempt before any shutdown wait or publication lock."""
        self.closing.set()
        # An immutable snapshot lets us signal without waiting for start().
        # An attempt racing registration also checks the shared closing event.
        for control in self._controls:
            control.event.set()

    def close(self, timeout=2):
        deadline = time.monotonic() + max(0, timeout)
        self.request_close()
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            return False
        try:
            self.closed = True
            jobs = list(self.jobs.values())
        finally:
            self.lock.release()
        for control, _ in jobs:
            control.cancel(timeout=max(0, deadline - time.monotonic()))
        for _, thread in jobs:
            thread.join(max(0, deadline - time.monotonic()))
        return all(not thread.is_alive() for _, thread in jobs)
