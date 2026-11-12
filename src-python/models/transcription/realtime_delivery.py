"""Bounded final translation, independent of capture and partial captions."""

from collections import OrderedDict
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread, current_thread
from time import monotonic

from .utterance_diagnostics import utterance_diagnostics


@dataclass
class _PendingFinal:
    update: object
    deadline: float
    publish: object
    admitted: object
    shown: bool
    committed: bool = False
    output_pending: bool = False


class _FinalGuard:
    def __init__(self, delivery, update, deadline):
        self.delivery, self.update, self.deadline = delivery, update, deadline

    def __call__(self):
        return self.delivery._current(self.update) and self.delivery._clock() < self.deadline

    def output(self, action):
        return self.delivery._output(self.update, action)


class RealtimeDelivery:
    def __init__(
        self,
        session,
        publish,
        process_final,
        on_error,
        *,
        clock=monotonic,
        on_stopped=None,
        admit=None,
    ):
        self.session = session
        self._publish, self._process, self._error = publish, process_final, on_error
        self._clock = clock
        self._on_stopped = on_stopped
        self._admit = admit
        self._stop = Event()
        self._finals = Queue(maxsize=4)
        self._terminal = OrderedDict()
        self._pending = {}
        self._pending_lock = Lock()
        self._threads = []

    def start(self):
        if self._threads or self._stop.is_set():
            raise RuntimeError("realtime_delivery_single_use")
        self._threads = [
            Thread(target=self._read, name="realtime-captions", daemon=True),
            Thread(target=self._translate, name="realtime-finals", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def request_stop(self):
        self._stop.set()
        self.session.request_stop()

    def close(self, timeout=3.0):
        self.request_stop()
        deadline = monotonic() + timeout
        for thread in self._threads:
            if thread is not current_thread():
                thread.join(max(0.0, deadline - monotonic()))
        utterance_diagnostics.flush(self.session.source)
        return all(not thread.is_alive() for thread in self._threads)

    def _current(self, update):
        return not self._stop.is_set() and self.session.is_current(update.namespace)

    @staticmethod
    def _payload(update):
        return dict(
            source=update.source,
            namespace=update.namespace,
            item_id=update.item_id,
            revision=update.revision,
            state=update.state,
            text=update.text,
            translations=[],
            expires_ns=update.received_ns + 2_000_000_000,
        )

    def _report(self, code, *, terminal=False):
        if terminal:
            self.request_stop()
        try:
            self._error(code)
        except Exception:
            # A diagnostics consumer cannot restart or strand capture.
            self.request_stop()

    def _reason(self, update, deadline, admitted):
        if not self._current(update) or not admitted():
            return "revoked"
        if self._clock() >= deadline:
            return "expired"
        return None

    def _output(self, update, action):
        # Reserve settlement without holding a lock over I/O. Only an explicit
        # success commits output; a gated/skipped sink must not count as sent.
        with self._pending_lock:
            pending = self._pending.get(update.item_id)
            if pending is None or self._reason(update, pending.deadline, pending.admitted):
                return False
            pending.output_pending = True
        committed = False
        try:
            committed = action() is True
            return committed
        finally:
            with self._pending_lock:
                pending.committed |= committed
                pending.output_pending = False

    def _settle(self, update, outcome, reason=None, result=None):
        # The reader (expiry/stop) and final worker compete for one outcome.
        # Never hold this lock across publication, rendering or a worker join.
        with self._pending_lock:
            pending = self._pending.get(update.item_id)
            if pending is None or (pending.output_pending and not pending.committed):
                return
            del self._pending[update.item_id]
        deadline, publish, admitted, shown = pending.deadline, pending.publish, pending.admitted, pending.shown
        invalid = self._reason(update, deadline, admitted)
        # Not a failure: the chatbox is switched off, and the row says so even
        # when the other outputs went out.
        chatbox_off = outcome == "delivered" and reason == "vrchat_off"
        if invalid:
            outcome, reason, result = "not_delivered", invalid, None
        try:
            if result is not None:
                payload = self._payload(update)
                payload.update(state="translated", revision=update.revision + 1,
                               original=result["original"], translations=result["translations"])
                shown = publish(payload) is not False or shown
        finally:
            # This only settles a shown row; it must survive revocation and
            # expiry. It never authorizes another output or a retry.
            invalid = self._reason(update, deadline, admitted)
            if invalid:
                outcome, reason = "not_delivered", invalid
            if pending.committed:
                # Later expiry/failure cannot undo an output that already left.
                outcome, reason = "delivered", "vrchat_off" if chatbox_off else None
            if shown:
                publish(dict(source=update.source, namespace=update.namespace,
                             item_id=update.item_id, revision=update.revision + 2,
                             state="outcome", outcome=outcome, reason=reason))

    def _settle_invalid(self):
        with self._pending_lock:
            pending = list(self._pending.values())
        for item in pending:
            reason = self._reason(item.update, item.deadline, item.admitted)
            if reason:
                self._settle(item.update, "not_delivered", reason)

    def _read(self):
        try:
            while not self._stop.is_set():
                self._settle_invalid()
                update = self.session.pop_update(0.05)
                if update is None:
                    if self.session.health()["state"] in (
                        "failed",
                        "closed",
                        "stopping",
                    ):
                        self.request_stop()
                    continue
                if not self._current(update) or update.item_id in self._terminal:
                    continue
                deadline = update.received_ns / 1e9 + 2.0
                now = self._clock()
                expired = not 0 < update.received_ns / 1e9 <= now or now >= deadline
                # A completed ASR item may have no recognized text. Retire its
                # provisional caption without asking a translator to invent a
                # message or sending an empty original to OSC/history.
                empty_final = update.is_final and not update.text.strip()
                payload = self._payload(update)
                if expired or empty_final:
                    payload.update(state="discarded", text="")
                if update.is_final or update.state == "discarded" or expired:
                    self._terminal[update.item_id] = None
                    if len(self._terminal) > 256:
                        self._terminal.popitem(last=False)
                # Voice ownership already belongs to the session's receipt.
                # Bind text delivery intent before publishing or queueing a final.
                publish, process, admitted = self._admit(update) if self._admit else (
                    self._publish, self._process, lambda: True)
                shown = publish(payload) is not False
                if update.is_final and not expired and not empty_final:
                    with self._pending_lock:
                        self._pending[update.item_id] = _PendingFinal(update, deadline, publish, admitted, shown)
                    reason = self._reason(update, deadline, admitted)
                    if reason:
                        self._settle(update, "not_delivered", reason)
                        continue
                    try:
                        self._finals.put_nowait((update, deadline, publish, process))
                    except Full:
                        self._settle(update, "failed", "queue_full")
                        self._report("realtime_final_queue_full", terminal=True)
        except Exception:
            self._report("realtime_caption_failed", terminal=True)
        finally:
            self._settle_invalid()
            if self._on_stopped is not None:
                try:
                    self._on_stopped()
                except Exception:
                    self._report("realtime_caption_cleanup_failed")

    def _translate(self):
        try:
            while not self._stop.is_set():
                try:
                    update, deadline, publish, process = self._finals.get(timeout=0.05)
                except Empty:
                    continue

                current = _FinalGuard(self, update, deadline)

                queue_ms = max(0.0, (self._clock() - update.received_ns / 1e9) * 1000)
                utterance_diagnostics.record(
                    update.source, "realtime_delivery", {"realtime_queue_ms": queue_ms},
                    f"[ASR-queue][{update.source}] realtime wait={queue_ms:.1f}ms",
                )
                if not current():
                    self._settle(update, "not_delivered")
                    continue
                try:
                    result = process(update, current)
                    if result is None:
                        self._settle(update, "not_delivered", "filtered")
                    else:
                        outcome = result.get("delivery_outcome", "delivered")
                        self._settle(update, outcome, result.get("delivery_reason"),
                                     result if outcome != "failed" else None)
                except Exception:
                    self._settle(update, "failed", "processing_failed")
                    if current():
                        self._report("realtime_final_failed")
                finally:
                    elapsed_ms = max(0.0, (self._clock() - update.received_ns / 1e9) * 1000)
                    utterance_diagnostics.record(
                        update.source, "realtime_processed", {"realtime_total_ms": elapsed_ms},
                        f"[latency][{update.source}] realtime delivery={elapsed_ms:.1f}ms queue={queue_ms:.1f}ms",
                    )
        finally:
            utterance_diagnostics.flush(self.session.source)
