"""One bounded, read-only PipeWire observation shared by control readers."""
import atexit
from dataclasses import dataclass
import json
import subprocess
import sys
from threading import Condition, Event, Lock, Thread, current_thread
import time

from runtime_paths import external_process_env

INTERVAL = .1
MAX_AGE = 1.0  # The previous readers allowed one second for pw-dump to complete.
MAX_BYTES = 8 * 1024 * 1024


class GraphUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Observation:
    sequence: int
    captured: float  # Monotonic time BEFORE enumeration, never receipt/parse time.
    data: object


class Subscription:
    def __init__(self, source, wake):
        self.source, self.wake = source, wake
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            self.source.release(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class GraphSource:
    def __init__(self, *, popen=None, clock=time.monotonic):
        self._popen, self._clock = popen, clock
        self._condition = Condition()
        self._lifecycle = Lock()
        self._users = set()
        self._thread = None
        self._stop = Event()
        self._closed = False
        self._observation = Observation(0, 0, None)

    def subscribe(self, wake=None):
        with self._lifecycle, self._condition:
            if self._closed:
                raise GraphUnavailable()
            user = Subscription(self, wake)
            self._users.add(user)
            return user

    def _publish(self, captured, data):
        with self._condition:
            self._observation = Observation(self._observation.sequence + 1, captured, data)
            self._condition.notify_all()
            for user in self._users:
                if user.wake is not None:
                    user.wake.set()

    def observation(self):
        with self._condition:
            return self._observation

    def _current(self):
        value = self._observation
        if (self._closed or value.data is None or self._thread is None
                or not self._thread.is_alive() or self._stop.is_set()
                or not 0 <= self._clock() - value.captured < MAX_AGE):
            raise GraphUnavailable()
        return value

    def read(self, *, wait=True, after=None):
        with self._condition:
            if self._closed:
                raise GraphUnavailable()
            if wait and self._thread is None and self._users:
                self._stop = Event()
                self._thread = Thread(target=self._work, name='vrct-pipewire-graph', daemon=True)
                self._thread.start()
            deadline = self._clock() + MAX_AGE
            initial = self._observation.sequence
            while True:
                try:
                    value = self._current()
                    if after is None or value.captured >= after:
                        return value
                except GraphUnavailable:
                    # Only initial acquisition may wait for unavailable data.
                    if (not wait or self._observation.data is not None
                            or self._observation.sequence != initial
                            or self._observation.captured > 0):
                        raise
                if (not wait or self._closed or self._stop.is_set()
                        or (self._thread is not None and not self._thread.is_alive())):
                    raise GraphUnavailable()
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise GraphUnavailable()
                self._condition.wait(remaining)

    def _dump(self):
        child = (self._popen or subprocess.Popen)(['pw-dump'], env=external_process_env(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            deadline = self._clock() + MAX_AGE
            while not self._stop.is_set():
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise GraphUnavailable()
                try:
                    wire, _ = child.communicate(timeout=min(.02, remaining))
                    if child.returncode or len(wire) > MAX_BYTES:
                        raise GraphUnavailable()
                    data = json.loads(wire)
                    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                        raise GraphUnavailable()
                    return data
                except subprocess.TimeoutExpired:
                    continue
            raise GraphUnavailable()
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            if child.stdout is not None:
                child.stdout.close()

    def _work(self):
        backoff = INTERVAL
        try:
            while not self._stop.is_set():
                captured = self._clock()
                try:
                    data = self._dump()
                    if self._stop.is_set() or self._clock() - captured >= MAX_AGE:
                        raise GraphUnavailable()
                    self._publish(captured, data)
                    backoff = INTERVAL
                    delay = max(0, INTERVAL - (self._clock() - captured))
                except Exception:
                    self._publish(captured, None)
                    delay, backoff = backoff, min(1.0, backoff * 2)
                self._stop.wait(delay)
        finally:
            self._publish(self._clock(), None)

    def release(self, user):
        with self._lifecycle:
            self._release(user)

    def _release(self, user):
        with self._condition:
            self._users.discard(user)
            if self._users:
                return
            self._stop.set()
            self._condition.notify_all()
            thread = self._thread
            # Serialize last release with a new subscriber; the worker only
            # needs this lock to publish its final unavailable observation.
        if thread is not None and thread is not current_thread():
            thread.join(MAX_AGE + INTERVAL)
        with self._condition:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None
                self._observation = Observation(self._observation.sequence + 1, 0, None)

    def close(self):
        with self._condition:
            self._closed = True
            self._users.clear()
        self.release(None)


_shared = GraphSource()
_remote = None


def graph_source():
    return _remote if _remote is not None else _shared


def read_graph(*, wait=True, after=None):
    if not sys.platform.startswith('linux'):
        raise GraphUnavailable()
    source = graph_source()
    if not wait:
        return source.read(wait=False, after=after)
    with source.subscribe():
        return source.read(after=after)


def shutdown():
    graph_source().close()


atexit.register(shutdown)
