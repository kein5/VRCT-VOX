"""Consent-gated file transactions; settings application is a separate explicit call."""
from copy import deepcopy
from dataclasses import asdict
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from threading import Event, RLock, Thread
import time
from urllib.parse import quote
from uuid import uuid4

from .catalog import CATALOG, CATALOG_VERSION, validate_catalog
from .guidance import model_guidance
from .transport import open_public
from .staging import RootLease, mark_owned, recover_owned

CHUNK = 1024 * 1024
ACTIVE = ('queued', 'downloading', 'verifying', 'cancelling')


class Cancelled(Exception):
    pass


def directory(path):
    """Create fixed directories while refusing symlink traversal."""
    if path.parent != path:
        directory(path.parent)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode):
        raise ValueError('unsafe_destination')


class Downloads:
    catalog_version = CATALOG_VERSION

    def __init__(self, root, *, catalog=CATALOG, transport=open_public, reserve_bytes=64 * 1024 * 1024):
        validate_catalog(catalog)
        self.root = Path(root).expanduser().absolute()
        self.entries = {m.id: m for m in catalog}
        self.transport, self.reserve_bytes = transport, reserve_bytes
        self.lock, self.closed = RLock(), False
        self.jobs, self.thread, self.cancel_event = {}, None, None
        self.response = None

    def destination(self, entry):
        return self.root / entry.id / entry.revision

    def catalog(self):
        return {'catalog_version': self.catalog_version, 'models': [dict(asdict(m),
                total_bytes=sum(a.size for a in m.artifacts), destination=str(self.destination(m)),
                source=f'https://huggingface.co/{m.repo}/tree/{m.revision}', guidance=model_guidance(m.id)) for m in self.entries.values()]}

    def state(self):
        with self.lock:
            return {'observation_id': str(time.monotonic_ns()), 'jobs': deepcopy(self.jobs)}

    def _job(self, id, job_id):
        job = self.jobs.get(id)
        if job is None or job['job_id'] != job_id:
            raise ValueError('stale_job')
        return job

    def start(self, request):
        if not isinstance(request, dict) or set(request) != {'id', 'consent', 'catalog_version'}:
            raise ValueError('download_request_invalid')
        if request['consent'] is not True:
            raise ValueError('consent_required')
        if (not isinstance(request['id'], str) or request['catalog_version'] != self.catalog_version
                or request['id'] not in self.entries):
            raise ValueError('catalog_changed')
        with self.lock:
            if self.closed:
                raise ValueError('downloads_closed')
            if self.thread is not None and self.thread.is_alive():
                raise ValueError('download_busy')
            entry = self.entries[request['id']]
            event = Event()
            self.jobs[entry.id] = dict(job_id=uuid4().hex, phase='queued', received_bytes=0,
                                      total_bytes=sum(a.size for a in entry.artifacts), paths={}, error_code=None)
            self.cancel_event = event
            self.thread = Thread(target=self._download, args=(entry, event), daemon=True, name='model-download')
            self.thread.start()
            return self.state()

    def cancel(self, id, job_id):
        with self.lock:
            job = self._job(id, job_id)
            if job['phase'] in ACTIVE:
                self.cancel_event.set()
                job['phase'] = 'cancelling'
                self._abort_body()
            return self.state()

    def _abort_body(self):
        if self.response is not None and hasattr(self.response, 'abort'):
            self.response.abort()

    def _checkpoint(self, event):
        if event.is_set():
            raise Cancelled()

    def _verify(self, path, artifact, event):
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('unsafe_destination')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            if os.fstat(stream.fileno()).st_size != artifact.size:
                raise ValueError('size_mismatch')
            digest = hashlib.sha256()
            while block := stream.read(CHUNK):
                self._checkpoint(event)
                digest.update(block)
            if digest.hexdigest() != artifact.sha256:
                raise ValueError('hash_mismatch')

    def _download(self, entry, event):
        staging = None
        lease = RootLease(self.root)
        job = self.jobs[entry.id]
        try:
            directory(self.root / entry.id)
            lease.acquire()
            recover_owned(self.root, self.entries)
            final = self.destination(entry)
            if final.exists() or final.is_symlink():
                directory(final)
                with self.lock: job['phase'] = 'verifying'
                for artifact in entry.artifacts:
                    self._verify(final / artifact.filename, artifact, event)
            else:
                if shutil.disk_usage(self.root).free < job['total_bytes'] + self.reserve_bytes:
                    raise ValueError('insufficient_space')
                staging = self.root / ('.partial-' + uuid4().hex)
                staging.mkdir(mode=0o700)
                mark_owned(staging, entry)
                for artifact in entry.artifacts:
                    self._checkpoint(event)
                    with self.lock: job['phase'] = 'downloading'
                    url = f'https://huggingface.co/{entry.repo}/resolve/{entry.revision}/{quote(artifact.filename)}'
                    digest, received = hashlib.sha256(), 0
                    with self.transport(url) as response, (staging / artifact.filename).open('xb') as output:
                        with self.lock:
                            self.response = response
                            self._checkpoint(event)
                        while block := response.read(CHUNK):
                            self._checkpoint(event)
                            received += len(block)
                            if received > artifact.size:
                                raise ValueError('size_mismatch')
                            output.write(block); digest.update(block)
                            with self.lock: job['received_bytes'] += len(block)
                        output.flush(); os.fsync(output.fileno())
                    self._checkpoint(event)
                    with self.lock: job['phase'] = 'verifying'
                    if received != artifact.size:
                        raise ValueError('size_mismatch')
                    if digest.hexdigest() != artifact.sha256:
                        raise ValueError('hash_mismatch')
                (staging / 'receipt.json').write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2))
            # Cancellation and publication have one linearization point.
            with self.lock:
                self._checkpoint(event)
                if staging is not None:
                    directory(final.parent)
                    if final.exists() or final.is_symlink():
                        raise ValueError('destination_exists')
                    staging.rename(final)
                    staging = None
                job.update(phase='ready', received_bytes=job['total_bytes'],
                           paths={a.role: str(final / a.filename) for a in entry.artifacts})
        except Cancelled:
            with self.lock: job.update(phase='cancelled', paths={})
        except Exception as error:
            known = {'insufficient_space', 'size_mismatch', 'hash_mismatch', 'unsafe_destination',
                     'destination_exists', 'download_url_rejected', 'download_http_error', 'download_busy'}
            code = str(error) if str(error) in known else 'download_failed'
            if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                code = 'insufficient_space'
            with self.lock:
                job.update(phase='cancelled' if event.is_set() else 'failed',
                           error_code=None if event.is_set() else code, paths={})
        finally:
            if staging is not None:
                try:
                    shutil.rmtree(staging)
                except OSError:
                    with self.lock: job.update(phase='failed', error_code='partial_cleanup_failed', paths={})
            lease.close()
            with self.lock: self.response = None

    def apply(self, id, job_id, callback):
        with self.lock:
            if self.closed:
                raise ValueError('downloads_closed')
            job = self._job(id, job_id)
            if job['phase'] != 'ready':
                raise ValueError('download_not_ready')
            entry = self.entries[id]
            directory(self.destination(entry))
            for artifact in entry.artifacts:
                self._verify(self.destination(entry) / artifact.filename, artifact, Event())
            callback(entry, deepcopy(job['paths']))
            job.update(phase='applied', error_code=None)
            return self.state()

    def close(self, timeout=2):
        with self.lock:
            self.closed = True
            if self.cancel_event is not None:
                self.cancel_event.set()
                self._abort_body()
            thread = self.thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()
