"""Control-only owner of a fixed, separately executed VC transport process."""
import os
from pathlib import Path
import select
import subprocess
from runtime_paths import resource_root, external_process_env
import sys
from threading import Event, Lock, Thread, current_thread, get_native_id
import time

from models.audio_routing.monitor_output import parse_monitor
from models.audio_routing.source_bridge import _source_id
from models.transcription.capture_pipewire import _validate
from .router_protocol import BASE_STATE, Reader, encode, validate_health
from .settings import start_options

ROOT = resource_root()
HELPER = ROOT / 'build/vrct-vc-worker'


def _launch():
    owner = os.pidfd_open(get_native_id(), os.O_EXCL)
    env = external_process_env()
    frozen = bool(getattr(sys, 'frozen', False))
    if not frozen:
        # Fixed application code, independent of the shell's PYTHONPATH.
        env['PYTHONPATH'] = str(ROOT / 'src-python') + os.pathsep + str(ROOT)
    try:
        return subprocess.Popen([str(HELPER), str(os.getpid()), str(owner), sys.executable,
            'router-frozen' if frozen else 'router'], cwd=ROOT, env=env, pass_fds=(owner,),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    finally:
        os.close(owner)


class IsolatedVCProcess:
    def __init__(self, options, monitor=None):
        from .direct_voice import create_worker_process
        self.options = start_options('converted', options)
        self.monitor = parse_monitor(monitor)
        for key in ('runtime', 'reference', 'model', 'index'):
            if self.options.get(key):
                self.options[key] = str(Path(self.options[key]).expanduser().resolve())
        create_worker_process(self.options)  # Existing local path checks; no capture/model load.
        self._state = dict(BASE_STATE)
        self._lock, self._stop = Lock(), Event()
        self._thread = self._child = None
        self._cleanup_ok = True

    def start(self, *, source):
        _validate(source, 'mic')
        request = dict(kind='start', source=_source_id(source), options=self.options)
        if self.monitor is not None:
            request['monitor'] = self.monitor
        request = encode(request)
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                raise RuntimeError('vc_single_use')
            self._state.update(requested=True, pending=True, state='preparing')
            self._thread = Thread(target=self._run, args=(request,), name='vrct-vc-owner', daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            self._state.update(requested=False, active=False, conversion_verified=False)

    def close(self, timeout=3):
        self.stop()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return (thread is None or not thread.is_alive()) and self._cleanup_ok

    def health(self):
        with self._lock:
            return dict(self._state, stopping=bool(self._thread and self._thread.is_alive()
                                                   and self._stop.is_set()))

    def _check(self):
        if self._stop.is_set():
            raise RuntimeError('cancelled')

    def _run(self, request):
        child = None
        try:
            self._check()
            child = self._child = _launch()
            os.set_blocking(child.stdin.fileno(), False)
            pending, deadline = memoryview(request), time.monotonic()+5
            while pending:
                self._check()
                if time.monotonic() >= deadline:
                    raise TimeoutError('vc_router_timeout')
                if select.select([], [child.stdin], [], .02)[1]:
                    try:
                        count = os.write(child.stdin.fileno(), pending)
                        if count <= 0:
                            raise EOFError
                        pending = pending[count:]
                    except BlockingIOError:
                        pass
            reader = Reader(child.stdout)
            while True:
                state = validate_health(reader.read(timeout=1, check=self._check))
                with self._lock:
                    self._check()
                    self._state.update(state)
                if state['error']:
                    break
        except Exception as exc:
            with self._lock:
                if not self._stop.is_set() and not self._state['error']:
                    self._state['error'] = ('vc_router_timeout' if isinstance(exc, TimeoutError)
                                            else 'vc_router_failed')
        finally:
            cancelled = self._stop.is_set()
            self.stop()
            if child is not None:
                try:
                    child.stdin.close()  # EOF requests cooperative audio cleanup.
                    try:
                        result = child.wait(timeout=2.2)
                        if result == 2:
                            self._cleanup_ok = False
                        if result and not cancelled and not self._state['error']:
                            self._state['error'] = 'vc_router_failed'
                    except subprocess.TimeoutExpired:
                        self._cleanup_ok = False
                        child.terminate()
                        try:
                            child.wait(timeout=.3)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=.3)
                    child.stdout.close()
                except Exception:
                    self._cleanup_ok = False
            with self._lock:
                self._state.update(pending=False, active=False, requested=False,
                                   state='failed' if self._state['error'] else 'stopped')
                if not self._cleanup_ok:
                    self._state['error'] = self._state['error'] or 'vc_cleanup_failed'
