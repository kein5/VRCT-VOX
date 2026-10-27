"""Control only: OS gate and durable intent; never processes audio samples."""
from threading import Condition, Event, Thread
import time


class VoiceRoute:
    def __init__(self, bus, *, gate, store, poll_interval=0.1):
        self.bus, self.gate, self.store = bus, gate, store
        self.poll_interval = poll_interval
        self._condition = Condition()
        self._wake = Event()
        self._thread = None
        self._closed = False
        self._managed = False
        self._identity = None
        self._revision = 0
        self._pending = False
        self._error = None
        self._ready = True
        try:
            self._desired = store.read()
        except Exception:
            self._desired, self._ready = True, False
            self._error = 'mute_state_unavailable'
        self.bus.set_muted(self._desired)
        self._observed = self._desired

    def status(self):
        with self._condition:
            return {'managed': self._managed, 'requested_muted': self._desired,
                    'observed_muted': self._observed, 'ready': self._ready,
                    'pending': self._pending, 'error': self._error,
                    'generation': self._revision, 'closed': self._closed}

    def _request_locked(self, muted):
        if self._closed:
            raise RuntimeError('voice_route_closed')
        self._desired = muted
        self._revision += 1
        self._pending = True
        self._error = None
        # Even resume keeps software closed until native + persistence confirmation.
        self.bus.set_muted(True)
        if self._thread is None:
            self._thread = Thread(target=self._work, name='vrct-voice-gate', daemon=True)
            self._thread.start()
        self._wake.set()

    def mute(self):
        with self._condition:
            self._request_locked(True)

    def resume(self):
        with self._condition:
            if not self._ready or self._pending:
                raise RuntimeError('voice_route_not_ready')
            self._request_locked(False)

    def configure(self, managed, timeout=3):
        with self._condition:
            if self._managed == managed:
                return
            if managed:
                self._managed = True
                self._identity = None
                self._observed = None
                self._ready = False
                self._request_locked(True)
                return
            # Keep current managed config until both native mute and durable intent confirm.
            self._request_locked(True)
            deadline = time.monotonic() + timeout
            while self._pending and time.monotonic() < deadline:
                self._condition.wait(deadline - time.monotonic())
            if self._pending or self._error or self._observed is not True:
                raise RuntimeError('managed_mute_unconfirmed')
            self._managed = False
            self._identity = None
            self._revision += 1
            self._wake.set()

    def _work(self):
        while True:
            self._wake.wait(self.poll_interval)
            self._wake.clear()
            with self._condition:
                if self._closed:
                    return
                managed, desired, revision = self._managed, self._desired, self._revision
                identity = self._identity
                if not managed and not self._pending:
                    continue
            observed = None
            try:
                if managed:
                    state = self.gate.inspect()
                    if identity != state['identity'] or (not self._pending and state['muted'] != desired):
                        # First attach, reconnect or external gate changes revoke resume.
                        with self._condition:
                            if revision != self._revision:
                                continue
                            self._desired = desired = True
                            self.bus.set_muted(True)
                            self._identity = state['identity']
                            self._revision += 1
                            revision = self._revision
                            self._pending = True
                    if state['muted'] != desired:
                        state = self.gate.set_muted(desired, state['identity'])
                    observed = state['muted']
                    if observed != desired:
                        raise RuntimeError('gate_change_unconfirmed')
                else:
                    observed = desired
                # No application setting write is mistaken for a durable latch.
                with self._condition:
                    if revision != self._revision:
                        self._wake.set()
                        continue
                    persist = self._pending
                if persist:
                    self.store.write(desired)
                with self._condition:
                    if revision != self._revision:
                        self._wake.set()
                        continue
                    self._observed = observed
                    self._ready, self._pending, self._error = True, False, None
                    self.bus.set_muted(desired)
                    self._condition.notify_all()
            except Exception as exc:
                with self._condition:
                    # A failed resume can never remain authorized for auto-retry.
                    self._desired = True
                    self.bus.set_muted(True)
                    self._revision += 1
                    self._observed = observed
                    self._ready, self._pending = False, True
                    self._error = (str(exc) if isinstance(exc, RuntimeError)
                                   else 'mute_state_unavailable')
                    self._condition.notify_all()

    def close(self, timeout=3):
        with self._condition:
            managed = self._managed
        if managed:
            try:
                self.configure(False, timeout=timeout)
            except RuntimeError:
                pass  # status retains the unconfirmed close; endpoint is never removed.
        with self._condition:
            self._closed = True
            self._revision += 1
            self.bus.set_muted(True)
            self._wake.set()
        if self._thread:
            self._thread.join(timeout)
        return self._thread is None or not self._thread.is_alive()
