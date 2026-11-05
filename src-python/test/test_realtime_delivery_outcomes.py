"""Correlated row outcomes with real controller/delivery and memory-only sinks."""

from threading import Event
from time import monotonic

import pytest

from test_message_delivery_revocation import app, captions, eventually, start, wait_for_finals  # noqa: F401


def outcomes(app):
    return [p for p in captions(app) if p["state"] == "outcome"]


def assert_outcome(app, item, outcome, reason=None):
    rows = [p for p in outcomes(app) if p["item_id"] == item]
    assert len(rows) == 1
    final = next(p for p in captions(app) if p["state"] == "final" and p["item_id"] == item)
    assert rows[0] == {**{key: final[key] for key in ("source", "generation", "namespace", "item_id")},
                       "revision": final["revision"] + 2, "state": "outcome",
                       "outcome": outcome, "reason": reason}


@pytest.mark.parametrize("source", ["mic", "speaker"])
def test_completion_follows_all_outputs_and_translation(app, source):
    session, delivery = start(app, source)
    app.m.logger.info.side_effect = lambda *args: outcomes(app) == [] or pytest.fail("early outcome")
    session.emit("recognized")
    wait_for_finals(session, delivery)
    assert_outcome(app, "recognized", "delivered")
    assert [p["state"] for p in captions(app)] == ["final", "translated", "outcome"]
    assert app.m.oscSendMessage.call_count == int(source == "mic")
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()


@pytest.mark.parametrize("output", ["oscSendMessage", "websocketSendMessage", "addTranslationHistory",
                                    "publishRealtimeCaptionOverlay"])
def test_output_exception_keeps_delivered_and_existing_warning(app, output):
    getattr(app.m, output).side_effect = RuntimeError("private output details")
    session, delivery = start(app)
    session.emit("recognized")
    wait_for_finals(session, delivery)
    assert_outcome(app, "recognized", "delivered")
    warnings = [call.args for call in app.c.run.call_args_list if call.args[1] == "/run/message_output_error"]
    assert warnings and all(row[2]["error_code"] == "MESSAGE_OUTPUT_FAILED" for row in warnings)
    assert "private output details" not in str(captions(app))
    app.m.logger.info.assert_called_once()


@pytest.mark.parametrize("reason", ["processing_failed", "filtered", "vram"])
def test_processing_failure_and_filter_are_distinct(app, reason):
    if reason == "filtered":
        app.m.checkKeywords.return_value = True
    else:
        app.m.getInputTranslate.side_effect = RuntimeError("private provider details")
        app.m.detectVRAMError = lambda error: (reason == "vram", "VRAM")
        app.c.setDisableTranslation = lambda: None
    session, delivery = start(app)
    session.emit("recognized")
    wait_for_finals(session, delivery)
    assert_outcome(app, "recognized", "not_delivered" if reason == "filtered" else "failed",
                   "filtered" if reason == "filtered" else "processing_failed")
    app.m.oscSendMessage.assert_not_called()


@pytest.mark.parametrize("cancel", ["expiry", "mute", "off", "shutdown"])
def test_blocked_and_queued_finals_settle_before_translation_returns(app, cancel):
    entered, release = Event(), Event()

    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return ["late"], [True], ["translated"]

    app.m.getInputTranslate.side_effect = translate
    session, delivery = start(app)
    try:
        session.emit("blocked")
        assert entered.wait(1)
        session.emit("queued")
        eventually(lambda: len([p for p in captions(app) if p["state"] == "final"]) == 2)
        if cancel == "expiry":
            expired_at = monotonic() + 3
            delivery._clock = lambda: expired_at
        elif cancel == "mute":
            app.mute()
            app.mute(False)
        elif cancel == "off":
            app.c.stopRealtimeASR({"source": "mic"})
        else:
            # Signal the actual shutdown invalidation without its bounded join.
            with app.c._realtime_lock:
                app.c._realtime_closed = True
                app.c._invalidateRealtimeLocked("mic")
        eventually(lambda: len(outcomes(app)) == 2)
        for item in ("blocked", "queued"):
            assert_outcome(app, item, "not_delivered", "expired" if cancel == "expiry" else "revoked")
        release.set()
        if cancel == "mute":
            wait_for_finals(session, delivery)
        else:
            assert delivery.close()
        assert len(outcomes(app)) == 2
        app.m.oscSendMessage.assert_not_called()
        app.m.websocketSendMessage.assert_not_called()
        app.m.logger.info.assert_not_called()
        assert app.m.getInputTranslate.call_count == 1
    finally:
        release.set()


@pytest.mark.parametrize("cancel", ["expiry", "mute", "off"])
@pytest.mark.parametrize("output", ["osc", "websocket"])
def test_committed_output_stays_delivered_while_later_sink_waits(app, cancel, output):
    entered, release = Event(), Event()
    app.cfg.ENABLE_CLIPBOARD = False
    app.cfg.SEND_MESSAGE_TO_VRC = output == "osc"
    app.m.checkWebSocketServerAlive.return_value = output == "websocket"

    def log(*args):
        entered.set()
        assert release.wait(2)

    app.m.logger.info.side_effect = log
    session, delivery = start(app)
    try:
        session.emit("committed")
        assert entered.wait(1)
        assert app.m.oscSendMessage.call_count == int(output == "osc")
        assert app.m.websocketSendMessage.call_count == int(output == "websocket")
        if cancel == "expiry":
            expired_at = monotonic() + 3
            delivery._clock = lambda: expired_at
        elif cancel == "mute":
            app.mute()
            app.mute(False)
        else:
            app.c.stopRealtimeASR({"source": "mic"})
        eventually(lambda: bool(outcomes(app)))
        assert_outcome(app, "committed", "delivered")
        release.set()
        assert delivery.close()
        assert_outcome(app, "committed", "delivered")
        app.m.addTranslationHistory.assert_not_called()
        assert app.c.voice_events.status()["accepted"] == 0
        assert not any(p["state"] == "translated" for p in captions(app))
    finally:
        release.set()


@pytest.mark.parametrize("output", ["websocket", "clipboard"])
def test_rejected_output_does_not_count_as_committed(app, output):
    app.cfg.SEND_MESSAGE_TO_VRC = False
    app.cfg.LOGGER_FEATURE = False
    app.cfg.ENABLE_CLIPBOARD = output == "clipboard"
    app.m.checkWebSocketServerAlive.return_value = output == "websocket"

    def reject(*args):
        app.mute()
        return False

    sink = app.m.websocketSendMessage if output == "websocket" else app.m.setCopyToClipboardAndPasteFromClipboard
    sink.side_effect = reject
    session, delivery = start(app)
    session.emit("rejected")
    wait_for_finals(session, delivery)
    sink.assert_called_once()
    assert_outcome(app, "rejected", "not_delivered", "revoked")


@pytest.mark.parametrize("succeeds", [True, False])
@pytest.mark.parametrize("cancel", ["expiry", "mute", "off"])
def test_outcome_waits_for_first_inflight_output_result(app, succeeds, cancel):
    entered, release = Event(), Event()
    app.cfg.ENABLE_CLIPBOARD = False

    def send(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        if not succeeds:
            raise RuntimeError("transport failed")
        return True

    app.m.oscSendMessage.side_effect = send
    session, delivery = start(app)
    try:
        session.emit("inflight")
        assert entered.wait(1)
        if cancel == "expiry":
            expired_at = monotonic() + 3
            delivery._clock = lambda: expired_at
        elif cancel == "mute":
            app.mute()
        else:
            app.c.stopRealtimeASR({"source": "mic"})
        delivery._settle_invalid()
        assert outcomes(app) == []
        release.set()
        eventually(lambda: bool(outcomes(app)))
        assert_outcome(app, "inflight", "delivered" if succeeds else "not_delivered",
                       None if succeeds else "expired" if cancel == "expiry" else "revoked")
        assert delivery.close()
        app.m.websocketSendMessage.assert_not_called()
    finally:
        release.set()


@pytest.mark.parametrize("other_outputs", [True, False])
def test_superseded_chatbox_outcome_accounts_for_other_committed_outputs(app, other_outputs):
    entered, release = Event(), Event()
    app.cfg.ENABLE_CLIPBOARD = False
    app.cfg.LOGGER_FEATURE = other_outputs
    app.m.checkWebSocketServerAlive.return_value = other_outputs
    assert app.c.voice_events.set_enabled(False)

    def translate(message, **kwargs):
        if message == "older":
            entered.set()
            assert release.wait(2)
        return ["translation"], [True], ["translated"]

    app.m.getInputTranslate.side_effect = translate
    session, delivery = start(app)
    try:
        session.emit("older")
        assert entered.wait(1)
        assert app.c.chatMessage({"id": "new", "message": "newer"})["status"] == 200
    finally:
        release.set()
    wait_for_finals(session, delivery)
    assert_outcome(app, "older", "delivered" if other_outputs else "not_delivered",
                   None if other_outputs else "superseded")
    app.m.oscSendMessage.assert_called_once()
    assert app.m.websocketSendMessage.call_count == 2 * int(other_outputs)
    assert app.m.logger.info.call_count == 2 * int(other_outputs)
    assert any(p["state"] == "translated" for p in captions(app))


def test_ui_rejected_final_has_no_outcome(app):
    session, delivery = start(app)
    app.mute()
    session.emit("unshown")
    eventually(lambda: "unshown" in delivery._terminal)
    assert delivery.close()
    assert captions(app) == []
    app.m.getInputTranslate.assert_not_called()


@pytest.mark.parametrize("recover", [False, True])
def test_ui_output_failure_keeps_other_outputs_and_only_settles_a_shown_row(app, recover):
    session, delivery = start(app)
    shown = []

    def publish(status, endpoint, payload):
        if endpoint == "/run/realtime_caption":
            if payload["state"] == "final" or (payload["state"] == "translated" and not recover):
                raise RuntimeError("UI unavailable")
            shown.append(payload)

    app.c.run.side_effect = publish
    session.emit("recognized")
    wait_for_finals(session, delivery)
    app.m.oscSendMessage.assert_called_once()
    app.m.websocketSendMessage.assert_called_once()
    app.m.logger.info.assert_called_once()
    assert [p["state"] for p in shown] == (["translated", "outcome"] if recover else [])
    assert sum(p["state"] == "outcome" for p in captions(app)) == int(recover)
