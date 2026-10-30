"""Inspect the fixed speech.cpp device list, without models or network access."""
from copy import deepcopy
import json
import subprocess
from threading import RLock, Thread
import time

from runtime_paths import external_process_env


def _bundled_binary():
    from models.speech_server.runtime import bundled_binary
    return bundled_binary()


def parse_devices(value):
    if not isinstance(value, dict) or not isinstance(value.get('devices'), list) or len(value['devices']) > 32:
        raise ValueError('hardware_invalid')
    rows, names = [], set()
    for row in value['devices']:
        if not isinstance(row, dict):
            raise ValueError('hardware_invalid')
        name, description, kind = (row.get(k) for k in ('name', 'description', 'kind'))
        if (any(not isinstance(s, str) or not s or len(s) > 256 or any(ord(c) < 32 for c in s)
                for s in (name, description)) or name in names or kind not in ('cpu', 'gpu', 'igpu')):
            raise ValueError('hardware_invalid')
        total, free = row.get('memory_total'), row.get('memory_free')
        if (any(v is not None and (type(v) is not int or not 0 <= v <= 2**53-1) for v in (total, free))
                or (total is not None and free is not None and free > total)):
            raise ValueError('hardware_invalid')
        # Zero total means the backend cannot report capacity. A zero free with
        # a known positive total is real exhaustion, never an unknown value.
        if not total:
            total, free = None, None
        names.add(name)
        rows.append(dict(name=name, description=description, kind=kind, memory_total=total, memory_free=free))
    return rows


class HardwareProbe:
    def __init__(self, *, binary=_bundled_binary, timeout=3):
        self.binary, self.timeout = binary, timeout
        self.lock = RLock()
        self.thread = self.child = None
        self.closed = False
        self._state = dict(phase='unknown', devices=[], measured_at_ms=None, error_code=None)

    def state(self):
        with self.lock:
            return dict(deepcopy(self._state), observation_id=str(time.monotonic_ns()))

    def refresh(self):
        with self.lock:
            if self.closed:
                raise ValueError('hardware_closed')
            if self.thread is None or not self.thread.is_alive():
                self._state.update(phase='probing', devices=[], measured_at_ms=None, error_code=None)
                self.thread = Thread(target=self._run, name='model-hardware', daemon=True)
                self.thread.start()
            return self.state()

    def _run(self):
        child = None
        try:
            binary = self.binary()
            with self.lock:
                if self.closed:
                    return
                child = self.child = subprocess.Popen([str(binary), 'devices', '--json'],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=dict(external_process_env(), SPEECH_NO_UPDATE_CHECK='1', NO_COLOR='1'))
            try:
                output, _ = child.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                child.kill(); child.communicate(timeout=1)
                raise ValueError('hardware_timeout') from None
            if child.returncode != 0:
                raise ValueError('hardware_failed')
            if len(output) > 65536:
                raise ValueError('hardware_invalid')
            try:
                rows = parse_devices(json.loads(output))
            except (ValueError, TypeError, UnicodeError):
                raise ValueError('hardware_invalid') from None
            with self.lock:
                if not self.closed:
                    self._state.update(phase='ready', devices=rows, measured_at_ms=int(time.time()*1000), error_code=None)
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) and str(exc) in (
                'hardware_timeout', 'hardware_failed', 'hardware_invalid') else 'hardware_unavailable'
            with self.lock:
                if not self.closed:
                    self._state.update(phase='failed', devices=[], error_code=code)
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=1)
                if child.stdout is not None:
                    child.stdout.close()
            with self.lock:
                self.child = None

    def close(self, timeout=2):
        deadline = time.monotonic() + max(0, timeout)
        with self.lock:
            self.closed = True
            self._state.update(phase='closed', devices=[])
            child, thread = self.child, self.thread
        if child is not None and child.poll() is None:
            try:
                child.terminate()
            except ProcessLookupError:
                pass
        if thread is not None:
            thread.join(min(.2, max(0, deadline-time.monotonic())))
            if child is not None and child.poll() is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            thread.join(max(0, deadline-time.monotonic()))
        return thread is None or not thread.is_alive()
