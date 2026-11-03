"""Process-exit subscriptions and one bounded probe worker per external address."""
from threading import Event, Lock, RLock, Thread, current_thread


class ListenerWatch:
    def __init__(self, monitor, token, stopped):
        self._monitor, self._token, self._stopped = monitor, token, stopped
        self._lock = RLock()
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
            self._monitor.remove(self)

    def unavailable(self):
        with self._lock:
            if not self._closed and not self._stopped.is_set():
                self._token.cancel('server_unavailable')

    def join(self):
        # An owned process waiter belongs to the runtime, not to a request.
        monitor = self._monitor
        if monitor.process is None and monitor.stopped.is_set():
            if monitor.thread is not current_thread():
                monitor.thread.join(.2)


class _ListenerMonitor:
    def __init__(self, registry, address, *, process=None, probe=None):
        self.registry, self.address = registry, address
        self.process, self.probe = process, probe
        self.watches = set()
        self.exited = False
        self.stopped = Event()
        self.thread = Thread(target=self._wait if process is not None else self._run,
                             name='vrct-speech-exit' if process is not None else 'vrct-vox-listener',
                             daemon=True)

    def remove(self, watch):
        with self.registry.lock:
            self.watches.discard(watch)
            if not self.watches:
                self.stopped.set()

    def _wait(self):
        try:
            self.process.wait()
        except OSError:
            # Failure to wait is not evidence of exit. HTTP deadlines still apply.
            return
        with self.registry.lock:
            self.exited = True
            watches = tuple(self.watches)
        for watch in watches:
            watch.unavailable()

    def _run(self):
        while True:
            self.stopped.wait(.02)
            with self.registry.lock:
                watches = tuple(self.watches)
            for watch in watches:
                if watch._stopped.is_set() or watch._token.is_set():
                    watch.close()
            with self.registry.lock:
                if not self.watches:
                    del self.registry.external[self.address]
                    return
                self.stopped.clear()
                watches = tuple(self.watches)
            if self.probe(self.address, self.stopped):
                # New subscribers must not inherit an observation made before
                # their request. Each cancellation is serialized with close().
                for watch in watches:
                    watch.unavailable()


class ListenerMonitors:
    def __init__(self):
        self.lock = Lock()
        self.owners = {}
        self.external = {}

    def own(self, address, process):
        monitor = _ListenerMonitor(self, address, process=process)
        with self.lock:
            self.owners[address] = monitor
            monitor.thread.start()
        return monitor

    def forget(self, monitor):
        with self.lock:
            if self.owners.get(monitor.address) is monitor:
                del self.owners[monitor.address]

    def owned(self, address):
        with self.lock:
            return self.owners.get(address)

    def watch(self, address, token, stopped, probe, *, owner=None):
        with self.lock:
            monitor = owner or self.external.get(address)
            start = monitor is None
            if start:
                monitor = _ListenerMonitor(self, address, probe=probe)
                self.external[address] = monitor
            watch = ListenerWatch(monitor, token, stopped)
            monitor.watches.add(watch)
            monitor.stopped.clear()
            exited = monitor.exited
            if start:
                monitor.thread.start()
        token.register(watch.close)
        if exited:
            watch.unavailable()
        return watch


listener_monitors = ListenerMonitors()
