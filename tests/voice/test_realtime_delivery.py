"""Slow translation must not stall partial captions or publish after stop."""

import importlib
from queue import Queue, Empty
from threading import Event
import time

import pytest

from models.transcription.realtime_events import TranscriptUpdate


def eventually(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


class Session:
    source = "mic"
    namespace = "owned"

    def __init__(self):
        self.updates = Queue()
        self.active = True
        self.clock = time.monotonic

    def pop_update(self, timeout=0.05):
        try:
            return self.updates.get(timeout=timeout)
        except Empty:
            return None

    def is_current(self, namespace):
        return self.active and namespace == self.namespace

    def request_stop(self):
        self.active = False

    def health(self):
        return dict(
            source=self.source,
            namespace=self.namespace,
            state="ready" if self.active else "closed",
        )

    def emit(self, item="u", final=False, revision=1, text="text"):
        self.updates.put(
            TranscriptUpdate(
                self.source,
                self.namespace,
                item,
                revision,
                text,
                final,
                "final" if final else "partial",
                received_ns=int(self.clock() * 1e9),
            )
        )


def create(session, publish, process, errors, **kwargs):
    session.clock = kwargs.get("clock", time.monotonic)
    module = importlib.import_module("models.transcription.realtime_delivery")
    return module.RealtimeDelivery(session, publish, process, errors.append, **kwargs)


def test_partials_replace_only_and_final_is_processed_once():
    session, published, processed, errors = Session(), [], [], []

    def process(update, current):
        assert current()
        processed.append(update.item_id)
        return {
            "original": {"message": update.text, "transliteration": []},
            "translations": [{"message": "translation", "transliteration": []}],
        }

    delivery = create(session, published.append, process, errors)
    try:
        delivery.start()
        session.emit(revision=1)
        session.emit(revision=2)
        eventually(lambda: len(published) == 2)
        assert processed == []
        session.emit(final=True, revision=3)
        session.emit(final=True, revision=3)
        eventually(lambda: any(p["state"] == "translated" for p in published))
        assert processed == ["u"]
        assert len([p for p in published if p["state"] == "final"]) == 1
        result = next(p for p in published if p["state"] == "translated")
        assert (
            result["revision"] == 4
            and result["namespace"] == "owned"
            and result["source"] == "mic"
        )
        assert result["translations"][0]["message"] == "translation"
        assert not errors
    finally:
        assert delivery.close()


@pytest.mark.parametrize("stop", [True, False])
def test_blocked_translation_cannot_publish_after_stop_or_expiry(stop):
    session, published, errors = Session(), [], []
    entered, release = Event(), Event()
    now = [100.0]
    effects = []

    def process(update, current):
        entered.set()
        release.wait(2)
        if current():
            effects.append("side_effect")
        return {"original": {"message": "text"}, "translations": [{"message": "late"}]}

    delivery = create(session, published.append, process, errors, clock=lambda: now[0])
    try:
        delivery.start()
        session.emit(final=True)
        assert entered.wait(1)
        session.emit("other")
        eventually(lambda: any(p["item_id"] == "other" for p in published))
        if stop:
            began = time.monotonic()
            delivery.request_stop()
            assert time.monotonic() - began < 0.1
        else:
            now[0] = 103
        release.set()
        time.sleep(0.08)
        assert not effects and not any(p["state"] == "translated" for p in published)
    finally:
        release.set()
        assert delivery.close()


def test_final_queue_overflow_stops_session_and_discards_queued_work():
    session, published, errors = Session(), [], []
    entered, release = Event(), Event()
    processed = []

    def process(update, current):
        processed.append(update.item_id)
        entered.set()
        release.wait(2)
        return None

    delivery = create(session, published.append, process, errors)
    try:
        delivery.start()
        session.emit("first", True)
        assert entered.wait(1)
        for i in range(5):
            session.emit(str(i), True)
        eventually(lambda: bool(errors))
        assert not session.active and errors == ["realtime_final_queue_full"]
        release.set()
        assert delivery.close()
        assert processed == ["first"]
    finally:
        release.set()
        delivery.close()


def test_expired_waiting_final_is_never_sent_to_translator():
    session, published, errors = Session(), [], []
    entered, release = Event(), Event()
    processed = []
    now = [100.0]

    def process(update, current):
        processed.append(update.item_id)
        entered.set()
        release.wait(2)
        return None

    delivery = create(session, published.append, process, errors, clock=lambda: now[0])
    try:
        delivery.start()
        session.emit("first", True)
        assert entered.wait(1)
        session.emit("second", True)
        eventually(lambda: any(p["item_id"] == "second" for p in published))
        now[0] = 103
        release.set()
        time.sleep(0.08)
        assert processed == ["first"]
    finally:
        release.set()
        assert delivery.close()


def test_translation_exception_is_safe_and_does_not_stop_other_captions():
    session, published, errors = Session(), [], []

    def process(update, current):
        raise RuntimeError("private provider body")

    delivery = create(session, published.append, process, errors)
    try:
        delivery.start()
        session.emit("first", True)
        eventually(lambda: bool(errors))
        session.emit("second")
        eventually(lambda: any(p["item_id"] == "second" for p in published))
        assert errors == ["realtime_final_failed"] and session.active
        assert "private" not in str(published)
    finally:
        assert delivery.close()


def test_busy_publisher_is_reported_and_stop_invalidates_capture():
    session, errors = Session(), []
    entered, release = Event(), Event()

    def publish(event):
        entered.set()
        release.wait(2)

    delivery = create(session, publish, lambda u, c: None, errors)
    try:
        delivery.start()
        session.emit()
        assert entered.wait(1)
        assert not delivery.close(timeout=0.05)
        assert not session.active
    finally:
        release.set()
        assert delivery.close()


def test_expiry_in_session_mailbox_does_not_restart_deadline():
    session, published, processed, errors = Session(), [], [], []
    now = [100.0]
    delivery = create(
        session,
        published.append,
        lambda u, c: processed.append(u.item_id),
        errors,
        clock=lambda: now[0],
    )
    session.emit("stale", True)
    now[0] = 103
    try:
        delivery.start()
        eventually(lambda: bool(published))
        assert processed == []
        assert published[0]["state"] == "discarded"
        assert published[0]["text"] == ""
    finally:
        assert delivery.close()


def test_stop_cleanup_is_owned_by_worker_and_never_blocks_fast_signal():
    session, errors = Session(), []
    entered, release = Event(), Event()

    def cleanup():
        entered.set()
        release.wait(2)

    delivery = create(
        session, lambda payload: None, lambda u, c: None, errors, on_stopped=cleanup
    )
    delivery.start()
    try:
        began = time.monotonic()
        delivery.request_stop()
        assert time.monotonic() - began < 0.1
        assert entered.wait(1)
        assert not delivery.close(0.02)
        release.set()
        assert delivery.close()
    finally:
        release.set()
        delivery.close()
