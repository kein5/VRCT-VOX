"""Bounded final translation, independent of capture and partial captions."""

from collections import OrderedDict
from queue import Empty, Full, Queue
from threading import Event, Thread, current_thread
from time import monotonic


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
    ):
        self.session = session
        self._publish, self._process, self._error = publish, process_final, on_error
        self._clock = clock
        self._on_stopped = on_stopped
        self._stop = Event()
        self._finals = Queue(maxsize=4)
        self._terminal = OrderedDict()
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

    def _read(self):
        try:
            while not self._stop.is_set():
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
                self._publish(payload)
                if update.is_final and not expired and not empty_final and self._current(update):
                    try:
                        self._finals.put_nowait((update, deadline))
                    except Full:
                        self._report("realtime_final_queue_full", terminal=True)
        except Exception:
            self._report("realtime_caption_failed", terminal=True)
        finally:
            if self._on_stopped is not None:
                try:
                    self._on_stopped()
                except Exception:
                    self._report("realtime_caption_cleanup_failed")

    def _translate(self):
        while not self._stop.is_set():
            try:
                update, deadline = self._finals.get(timeout=0.05)
            except Empty:
                continue

            def current():
                return self._current(update) and self._clock() < deadline

            if not current():
                continue
            try:
                result = self._process(update, current)
                if result is not None and current():
                    payload = self._payload(update)
                    payload.update(
                        state="translated",
                        revision=update.revision + 1,
                        original=result["original"],
                        translations=result["translations"],
                    )
                    self._publish(payload)
            except Exception:
                if current():
                    self._report("realtime_final_failed")
