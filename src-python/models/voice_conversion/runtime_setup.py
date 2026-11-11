"""Consent-gated setup of an external voice conversion runtime (Windows, Linux x86-64).

Torch and the engines stay out of the application. This process fetches pinned files,
runs a pinned uv over the hash-locked requirements, and never imports the result.
A failed or cancelled setup keeps each finished step and continues from there.
"""
from dataclasses import asdict, dataclass
import errno
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
from threading import Event, RLock, Thread
import time
from urllib.parse import quote
from uuid import uuid4
import zipfile

from models.model_downloads.staging import RootLease
from models.model_downloads.transport import HOSTS, open_public
from models.owned_child import launch_owned
from runtime_paths import external_process_env

CHUNK = 1024 * 1024
ACTIVE = ('queued', 'tools', 'python', 'packages', 'engine', 'assets', 'verifying', 'cancelling')
STEPS = ('tools', 'python', 'packages', 'engine', 'assets', 'verifying')
# The step that failed says what the user can do about it.
STEP_ERRORS = {'tools': 'vc_runtime_tools_failed', 'python': 'vc_runtime_python_failed',
               'packages': 'vc_runtime_packages_failed', 'engine': 'vc_runtime_source_failed',
               'assets': 'vc_runtime_assets_failed', 'verifying': 'vc_runtime_gpu_unusable'}



@dataclass(frozen=True)
class Tool:
    """One platform's uv release file."""
    url: str
    size: int
    sha256: str
    member: str  # uv inside the archive.


UV_VERSION = '0.13.7'
UV_RELEASE = f'https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/'
# The hashes are the ones the release publishes next to each file.
UV = {'win32': Tool(UV_RELEASE + 'uv-x86_64-pc-windows-msvc.zip', 15236317,
                    '0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021', 'uv.exe'),
      'linux': Tool(UV_RELEASE + 'uv-x86_64-unknown-linux-gnu.tar.gz', 16671812,
                    'c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83',
                    'uv-x86_64-unknown-linux-gnu/uv')}
# GitHub serves releases and source archives from these hosts. uv itself fetches Python
# and packages, and checks them against what it pins and the lock files.
SOURCE_HOSTS = HOSTS | {'github.com', 'codeload.github.com', 'objects.githubusercontent.com',
                        'release-assets.githubusercontent.com'}
SOURCE_LIMIT = 64 * 1024 * 1024
CUDA_INDEX = 'https://download.pytorch.org/whl/cu128'
CUDA_CHECK = 'import sys, torch; sys.exit(0 if torch.cuda.is_available() else 3)'
RVC_REPO, RVC_REVISION = 'lj1995/VoiceConversionWebUI', 'e6d0c1a17da07c33557852f9dfa2bd44cc75737d'
RVC_COMMIT = '81eed5e8f68b6bed1789f682fe78cdd324495afc'
SEED_COMMIT = '58d0ca372cc76f60a798d9f84611f053f9029f3a'
SEED_DIGEST = '106613138abf328fd382ba211709675399f11e76f720abfd4ab54eb2bac2b755'  # After the patch.
SEED_MANIFEST = 'docs/voice-stack/seed-vc-poc-artifacts.json'
HUNK = re.compile(r'@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@')
# The NVIDIA kernel driver publishes this while it is loaded; nouveau does not.
LINUX_DRIVER = Path('/proc/driver/nvidia/version')


def target():
    """The platform a runtime can be set up for, or ''. The Linux locks name x86-64 wheels."""
    if sys.platform == 'win32':
        return 'win32'
    return 'linux' if sys.platform == 'linux' and platform.machine() == 'x86_64' else ''


def runtime_python(folder):
    """The same file rvc_process.runtime_python starts."""
    return folder / ('venv/Scripts/python.exe' if target() == 'win32' else 'venv/bin/python')


def worker_file(path):
    # Importing the process stack waits until a setup page needs it, not app start.
    from .rvc_process import worker_root
    return worker_root() / path


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    url: str
    path: str  # Under the runtime's assets folder.
    size: int
    sha256: str = ''
    blob: str = ''  # Git blob id, for small files whose source lists no SHA-256.


@dataclass(frozen=True)
class Runtime:
    id: str
    name: str
    python: str
    locks: tuple  # (path under the worker root, package index or '').
    source_url: str
    source_digest: str
    patch: str  # Path under the worker root, or ''.
    assets: tuple
    license: str
    licenses: tuple
    notice: str
    download_bytes: int
    disk_bytes: int


def hf_url(repo, revision, path):
    return f'https://huggingface.co/{repo}/resolve/{revision}/{quote(path, safe="/")}'


# What differs by platform: the lock files, then the download and free space shown before
# consent. The sizes are rounded up from one measured setup on each platform.
RVC_PLATFORM = {
    'win32': ((('integrations/rvc/requirements-cuda-windows.lock', CUDA_INDEX),
               ('integrations/rvc/requirements-windows.lock', '')), 3_600_000_000, 12_000_000_000),
    'linux': ((('integrations/rvc/requirements-cuda.lock', CUDA_INDEX),
               ('integrations/rvc/requirements.lock', '')), 4_900_000_000, 16_000_000_000)}
SEED_PLATFORM = {
    'win32': ((('integrations/seed_vc/requirements-windows.lock', ''),), 5_000_000_000, 14_000_000_000),
    'linux': ((('integrations/seed_vc/requirements.lock', ''),), 6_400_000_000, 18_000_000_000)}


def rvc_runtime():
    locks, download, disk = RVC_PLATFORM[target()]
    return Runtime(
        'rvc', 'RVC', '3.12', locks,
        f'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/archive/{RVC_COMMIT}.zip',
        '9778a961cda108fd3145f36ae14d7ba9401308e610920157903bc219231f93fd', '',
        (Asset(hf_url(RVC_REPO, RVC_REVISION, 'hubert_base/config.json'), 'hubert_base/config.json', 1492,
               '0346950779dfb7f9316fa74ed846e2b8a22a08eedfdc5387b73f327cb1a4a7cf'),
         Asset(hf_url(RVC_REPO, RVC_REVISION, 'hubert_base/preprocessor_config.json'), 'hubert_base/preprocessor_config.json', 225,
               '7c1976a680fb7acc757cd36fb08eef878fa36c70b4c9d2d595df9c608bbbbf0e'),
         Asset(hf_url(RVC_REPO, RVC_REVISION, 'hubert_base/pytorch_model.bin'), 'hubert_base/pytorch_model.bin', 189206711,
               'cc8c20f4b90a520757260197a3ff2505705a7adbd20ad9eeaa4e1a9b38442ef5'),
         Asset(hf_url(RVC_REPO, RVC_REVISION, 'rmvpe.pt'), 'rmvpe/rmvpe.pt', 181184272,
               '6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193')),
        'MIT, BSD-3-Clause, GPL-3.0, NVIDIA CUDA EULA',
        (f'https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/{RVC_COMMIT}/LICENSE',
         f'https://huggingface.co/{RVC_REPO}', 'https://github.com/pytorch/pytorch/blob/main/LICENSE',
         'https://docs.nvidia.com/cuda/eula/index.html'),
        'rvc', download, disk)


def seed_assets(manifest):
    """The reviewed Seed-VC files, in the layout its offline loader reads."""
    rows = []
    for item in manifest['files']:
        lfs = item.get('lfs') or {}
        rows.append(Asset(hf_url(item['repo'], item['revision'], item['rfilename']),
                          f"{item['repo']}/{item['revision']}/{item['rfilename']}", item['size'],
                          lfs.get('sha256', ''), '' if lfs else item['blobId']))
    return tuple(rows)


def seed_runtime():
    manifest = json.loads(worker_file(SEED_MANIFEST).read_text(encoding='utf-8'))
    locks, download, disk = SEED_PLATFORM[target()]
    return Runtime(
        'seed-vc', 'Seed-VC', '3.11', locks,
        f'https://github.com/jiaheguo521/seed-vc-realtime/archive/{SEED_COMMIT}.zip', SEED_DIGEST,
        'integrations/seed_vc/offline-loader.patch', seed_assets(manifest),
        'GPL-3.0, Apache-2.0, BSD-3-Clause, NVIDIA CUDA EULA',
        (f'https://github.com/jiaheguo521/seed-vc-realtime/blob/{SEED_COMMIT}/LICENSE',
         'https://huggingface.co/Plachta/Seed-VC', 'https://huggingface.co/funasr/fsmn-vad',
         'https://huggingface.co/funasr/campplus', 'https://huggingface.co/FunAudioLLM/CosyVoice-300M',
         'https://huggingface.co/facebook/wav2vec2-xls-r-300m', 'https://github.com/pytorch/pytorch/blob/main/LICENSE',
         'https://docs.nvidia.com/cuda/eula/index.html'),
        'seed', download, disk)


def runtimes():
    """What this platform can set up."""
    if not target():
        return ()
    return (rvc_runtime(), seed_runtime())


def source_digest(root):
    """integrations.rvc.loader.source_digest, which the sidecar cannot import when frozen."""
    root = Path(root)
    digest = hashlib.sha256()
    for name in sorted(file.relative_to(root).as_posix() for file in root.rglob('*.py')):
        digest.update(name.encode() + b'\0' + hashlib.sha256((root / name).read_bytes()).digest())
    return digest.hexdigest()


@lru_cache(maxsize=None)
def version_of(runtime):
    """Changes with anything the user consented to or that changes the install."""
    digest = hashlib.sha256(json.dumps([asdict(runtime), UV_VERSION, UV[target()].sha256], sort_keys=True).encode())
    for path, _ in runtime.locks:
        digest.update(hashlib.sha256(worker_file(path).read_bytes()).digest())
    return digest.hexdigest()[:16]


def nvidia_driver():
    """The CUDA builds of Torch need this driver; it is present with any NVIDIA GPU.

    Only a file is looked for. Torch answers for itself once the runtime is installed.
    """
    if target() == 'win32':
        return (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/nvcuda.dll').is_file()
    return LINUX_DRIVER.is_file()


class _Group(subprocess.Popen):
    """uv and whatever it starts, such as a package's build, stopped together."""
    def kill(self):
        if self.poll() is None:
            os.killpg(self.pid, signal.SIGKILL)


def launch_group(args, *, stdin=None, stdout=None, stderr=None, env=None, cwd=None):
    """Linux: a child that ends with this process, as the Windows job object promises.

    The helper that owns the audio workers starts fixed programs only, so uv gets the
    kernel's parent-death signal instead. It follows the thread that started the child,
    which is the setup thread that also waits for it.
    """
    import ctypes
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    prctl.argtypes = (ctypes.c_int,) + (ctypes.c_ulong,) * 4
    parent, death_signal, kill = os.getpid(), 1, int(signal.SIGKILL)  # PR_SET_PDEATHSIG

    def tie():
        # Between fork and exec. The parent may already be gone by now.
        if prctl(death_signal, kill, 0, 0, 0) != 0 or os.getppid() != parent:
            os._exit(127)

    return _Group(args, stdin=stdin, stdout=stdout, stderr=stderr, env=env, cwd=cwd,
                  start_new_session=True, preexec_fn=tie)


def launch(args, **options):
    return (launch_owned if target() == 'win32' else launch_group)(args, **options)


def unpack_source(archive, target):
    """A GitHub archive without its one top folder."""
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            parts = PurePosixPath(entry.filename).parts[1:]
            if entry.is_dir() or not parts:
                continue
            if '..' in parts or re.search(r'[:\\]', entry.filename):
                raise ValueError('source_path_unsafe')
            path = target.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as reader, path.open('wb') as writer:
                shutil.copyfileobj(reader, writer)


def apply_patch(root, text):
    """A unified diff whose context must match exactly. A Windows PC has no patch tool."""
    rows = text.split('\n')
    index = 0
    while index < len(rows):
        if not rows[index].startswith('+++ b/'):
            index += 1
            continue
        path = root / rows[index][6:].strip()
        data = path.read_bytes().decode('utf-8')
        newline = '\r\n' if '\r\n' in data else '\n'
        lines = data.split(newline)
        index += 1
        moved = 0
        while index < len(rows) and (match := HUNK.match(rows[index])):
            at = int(match[1]) - 1 + moved
            index += 1
            while index < len(rows) and rows[index][:1] in (' ', '+', '-', '\\'):
                kind, line = rows[index][:1], rows[index][1:]
                index += 1
                if kind == '\\':
                    continue
                if kind == '+':
                    lines.insert(at, line)
                    at, moved = at + 1, moved + 1
                    continue
                if at >= len(lines) or lines[at] != line:
                    raise ValueError('patch_mismatch')
                if kind == '-':
                    del lines[at]
                    moved -= 1
                else:
                    at += 1
        path.write_bytes(newline.join(lines).encode('utf-8'))


def _new_digest(size, sha256, blob):
    if blob and not sha256:
        return hashlib.sha1(f'blob {size}\0'.encode(), usedforsecurity=False)
    return hashlib.sha256()


def _file_digest(path, asset, check):
    digest = _new_digest(asset.size, asset.sha256, asset.blob)
    with path.open('rb') as stream:
        while block := stream.read(CHUNK):
            check()
            digest.update(block)
    return digest.hexdigest()


class RuntimeSetup:
    def __init__(self, root, *, transport=open_public, launcher=launch, entries=None, gpu_check=nvidia_driver):
        self.root = Path(root).expanduser().absolute()
        self._entries = None if entries is None else {runtime.id: runtime for runtime in entries}
        self.transport, self.launcher, self.gpu_check = transport, launcher, gpu_check
        self.lock = RLock()
        self.closing = Event()
        self.closed = False
        self.jobs = {}
        self.thread = self.cancel_event = self.response = self.child = None

    @property
    def entries(self):
        # Reading these needs the worker's files, so it waits until a setup page opens.
        if self._entries is None:
            self._entries = {runtime.id: runtime for runtime in runtimes()}
        return self._entries

    def folder(self, runtime):
        return self.root / runtime.id

    def _installed(self, runtime):
        folder = self.folder(runtime)
        try:
            receipt = json.loads((folder / 'receipt.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        # What the worker refuses to start without, so a damaged runtime can be set up again.
        return (isinstance(receipt, dict) and receipt.get('version') == version_of(runtime)
                and runtime_python(folder).is_file()
                and (folder / 'engine').is_dir() and (folder / 'assets').is_dir())

    def catalog(self):
        rows = []
        gpu = self.gpu_check() if self.entries else False
        for runtime in self.entries.values():
            rows.append(dict(id=runtime.id, name=runtime.name, version=version_of(runtime), license=runtime.license,
                             licenses=list(runtime.licenses), notice=runtime.notice, download_bytes=runtime.download_bytes,
                             disk_bytes=runtime.disk_bytes, destination=str(self.folder(runtime)), gpu_ready=gpu))
        return {'runtimes': rows}

    def state(self):
        with self.lock:
            return {'observation_id': str(time.monotonic_ns()), 'jobs': {key: dict(job) for key, job in self.jobs.items()},
                    'installed': {runtime.id: str(self.folder(runtime)) for runtime in self.entries.values()
                                  if self._installed(runtime)}}

    def start(self, request):
        if not isinstance(request, dict) or set(request) != {'id', 'consent', 'version'}:
            raise ValueError('vc_runtime_request_invalid')
        if request['consent'] is not True:
            raise ValueError('consent_required')
        runtime = self.entries.get(request['id']) if isinstance(request['id'], str) else None
        if runtime is None or request['version'] != version_of(runtime):
            raise ValueError('vc_runtime_changed')
        with self.lock:
            if self.closed or self.closing.is_set():
                raise ValueError('vc_runtime_closed')
            if any(job['phase'] in ACTIVE for job in self.jobs.values()):
                raise ValueError('vc_runtime_busy')
            event = Event()
            self.jobs[runtime.id] = dict(job_id=uuid4().hex, phase='queued', step=0, steps=len(STEPS), received_bytes=0,
                                         total_bytes=0, error_code=None, path=None)
            self.cancel_event = event
            self.thread = Thread(target=self._install, args=(runtime, event, self.thread), daemon=True, name='vc-runtime-setup')
            self.thread.start()
            return self.state()

    def cancel(self, id, job_id):
        with self.lock:
            job = self.jobs.get(id)
            if job is None or job['job_id'] != job_id:
                raise ValueError('stale_job')
            if job['phase'] in ACTIVE:
                self.cancel_event.set()
                job['phase'] = 'cancelling'
                self._interrupt()
            return self.state()

    def _interrupt(self):
        if self.response is not None and hasattr(self.response, 'abort'):
            self.response.abort()
        if self.child is not None:
            self.child.kill()

    def _checkpoint(self, event):
        if event.is_set() or self.closing.is_set():
            raise Cancelled()

    def _fetch(self, url, target, event, job=None, *, size=None, sha256='', blob='', limit=None):
        part = target.with_name(target.name + '.part')
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = _new_digest(size, sha256, blob)
        received = 0
        with self.transport(url, hosts=SOURCE_HOSTS) as response, part.open('wb') as output:
            with self.lock:
                self.response = response
                self._checkpoint(event)
            while block := response.read(CHUNK):
                self._checkpoint(event)
                received += len(block)
                if received > (size if size is not None else limit):
                    raise ValueError('size_mismatch')
                output.write(block)
                digest.update(block)
                if job is not None:
                    with self.lock:
                        job['received_bytes'] += len(block)
        with self.lock:
            self.response = None
        if (size is not None and received != size) or digest.hexdigest() != (sha256 or blob or digest.hexdigest()):
            part.unlink(missing_ok=True)
            raise ValueError('hash_mismatch')
        os.replace(part, target)

    def _uv(self):
        return self.root / f'.uv-{UV_VERSION}' / ('uv.exe' if target() == 'win32' else 'uv')

    def _run(self, runtime, event, args):
        folder = self.folder(runtime)
        env = external_process_env()
        env.pop('VIRTUAL_ENV', None)
        env.update(UV_CACHE_DIR=str(folder / '.cache'), UV_PYTHON_INSTALL_DIR=str(folder / 'python'), UV_NO_PROGRESS='1')
        with (folder / 'setup.log').open('ab') as log:
            child = self.launcher([str(value) for value in args], stdin=subprocess.DEVNULL, stdout=log,
                                  stderr=subprocess.STDOUT, env=env, cwd=str(folder))
            with self.lock:
                self.child = child
            try:
                while True:
                    try:
                        code = child.wait(.2)
                        break
                    except subprocess.TimeoutExpired:
                        if event.is_set() or self.closing.is_set():
                            child.kill()
                            child.wait()
                            raise Cancelled() from None
            finally:
                with self.lock:
                    self.child = None
        self._checkpoint(event)
        if code:
            raise ValueError('step_failed')

    def _tools(self, runtime, event, job):
        uv, tool = self._uv(), UV[target()]
        if uv.is_file():
            return
        packed = tool.url.endswith('.zip')
        archive, part = uv.with_name('uv.zip' if packed else 'uv.tar.gz'), uv.with_name('uv.part')
        self._fetch(tool.url, archive, event, size=tool.size, sha256=tool.sha256)
        if packed:
            with zipfile.ZipFile(archive) as source:
                part.write_bytes(source.read(tool.member))
        else:
            with tarfile.open(archive, 'r:gz') as source, source.extractfile(tool.member) as reader:
                part.write_bytes(reader.read())
            part.chmod(0o755)
        os.replace(part, uv)
        archive.unlink()

    def _python(self, runtime, event, job):
        self._run(runtime, event, [self._uv(), 'venv', '--no-config', '--managed-python', '--clear',
                                   '--python', runtime.python, self.folder(runtime) / 'venv'])

    def _packages(self, runtime, event, job):
        python = runtime_python(self.folder(runtime))
        for path, index in runtime.locks:
            args = [self._uv(), 'pip', 'install', '--no-config', '--python', python, '--require-hashes']
            self._run(runtime, event, args + (['--index-url', index] if index else []) + ['-r', worker_file(path)])

    def _engine(self, runtime, event, job):
        folder = self.folder(runtime)
        archive, staging, target = folder / 'engine.zip', folder / 'engine.part', folder / 'engine'
        shutil.rmtree(staging, ignore_errors=True)
        self._fetch(runtime.source_url, archive, event, limit=SOURCE_LIMIT)
        unpack_source(archive, staging)
        if runtime.patch:
            apply_patch(staging, worker_file(runtime.patch).read_text(encoding='utf-8'))
        if source_digest(staging) != runtime.source_digest:
            raise ValueError('hash_mismatch')
        shutil.rmtree(target, ignore_errors=True)
        os.replace(staging, target)
        archive.unlink()

    def _assets(self, runtime, event, job):
        with self.lock:
            job['total_bytes'] = sum(asset.size for asset in runtime.assets)
        for asset in runtime.assets:
            target = self.folder(runtime) / 'assets' / asset.path
            if (target.is_file() and target.stat().st_size == asset.size
                    and _file_digest(target, asset, lambda: self._checkpoint(event)) == (asset.sha256 or asset.blob)):
                with self.lock:
                    job['received_bytes'] += asset.size
                continue
            self._fetch(asset.url, target, event, job, size=asset.size, sha256=asset.sha256, blob=asset.blob)

    def _verifying(self, runtime, event, job):
        self._run(runtime, event, [runtime_python(self.folder(runtime)), '-c', CUDA_CHECK])

    def _install(self, runtime, event, previous=None):
        if previous is not None:
            previous.join()
        job = self.jobs[runtime.id]
        folder = self.folder(runtime)
        marker = folder / '.steps.json'
        version = version_of(runtime)
        lease = RootLease(self.root)
        terminal, step = None, 'tools'
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            lease.acquire()
            folder.mkdir(exist_ok=True)
            self._uv().parent.mkdir(exist_ok=True)
            try:
                finished = json.loads(marker.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                finished = {}
            if not isinstance(finished, dict) or finished.get('version') != version:
                finished = {'version': version, 'steps': []}
            if not finished['steps'] and shutil.disk_usage(self.root).free < runtime.disk_bytes:
                raise OSError(errno.ENOSPC, 'space')
            for number, step in enumerate(STEPS, 1):
                self._checkpoint(event)
                with self.lock:
                    if job['phase'] != 'cancelling':
                        job.update(phase=step, step=number, received_bytes=0, total_bytes=0)
                if step in finished['steps']:
                    continue
                getattr(self, '_' + step)(runtime, event, job)
                finished['steps'].append(step)
                marker.write_text(json.dumps(finished), encoding='utf-8')
            self._checkpoint(event)
            (folder / 'receipt.json').write_text(json.dumps({'version': version, 'id': runtime.id}), encoding='utf-8')
            # Steps resume a setup, not a finished runtime: a repair must run them again.
            marker.unlink(missing_ok=True)
            shutil.rmtree(folder / '.cache', ignore_errors=True)
            terminal = dict(phase='ready', path=str(folder), error_code=None)
        except Cancelled:
            terminal = dict(phase='cancelled')
        except Exception as error:
            code = STEP_ERRORS[step]
            if str(error) == 'download_busy':
                code = 'vc_runtime_busy'
            elif isinstance(error, OSError) and error.errno == errno.ENOSPC:
                code = 'vc_runtime_space'
            terminal = (dict(phase='cancelled') if event.is_set() or self.closing.is_set()
                        else dict(phase='failed', error_code=code))
        finally:
            lease.close()
            with self.lock:
                self.response = self.child = None
                job.update(terminal or dict(phase='failed', error_code='vc_runtime_failed'))

    def request_close(self):
        """Signal cancellation without waiting for a worker."""
        self.closing.set()
        event = self.cancel_event
        if event is not None:
            event.set()

    def close(self, timeout=2):
        deadline = time.monotonic() + max(0, timeout)
        self.request_close()
        if not self.lock.acquire(timeout=max(0, timeout)):
            return False
        try:
            self.closed = True
            self._interrupt()
            thread = self.thread
        finally:
            self.lock.release()
        if thread is not None:
            thread.join(max(0, deadline - time.monotonic()))
        return thread is None or not thread.is_alive()
