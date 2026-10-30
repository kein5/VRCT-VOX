import base64
import json
import os
from urllib.parse import urlsplit

import pytest
from test_speech_servers_ui import ui as ui

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ['ui']

pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_SPEECH_UI") != "1", reason="opt-in browser"
)


def test_quick_chat_focus_ime_pending_once_and_escape(ui):
    from playwright.sync_api import expect

    page, _, _ = ui
    url = urlsplit(page.url)
    page.goto(f"{url.scheme}://{url.netloc}/tests/voice/quick-chat-entry/")
    field = page.get_by_role("textbox", name="Message", exact=True)
    expect(field).to_be_focused()
    field.fill("   ")
    field.press("Enter")
    assert page.evaluate("window.sent") == []
    field.fill("日本語の変換")
    field.dispatch_event("compositionstart")
    field.press("Enter")
    assert page.evaluate("window.sent") == []
    field.dispatch_event("compositionend")
    # Synthetic composition events do not install a real IME. Supply the
    # committed value (plain Chromium otherwise inserts LF on the test Enter).
    field.fill("日本語の変換")
    page.evaluate("window.hold = true")
    field.press("Enter")
    field.press("Enter")
    page.evaluate("window.release()")
    expect(field).to_have_value("")
    sent = page.evaluate("window.sent")
    assert len(sent) == 1 and sent[0]["endpoint"] == "/run/send_message_box"
    assert json.loads(base64.b64decode(sent[0]["data"]))["message"] == "日本語の変換"
    field.fill("keep draft")
    field.press("Escape")
    assert page.evaluate("window.quickChatHidden")
    expect(field).to_have_value("keep draft")
    page.evaluate("window.quickChatHidden = false")
    field.press("Tab")
    page.get_by_role("button", name="Send", exact=True).press("Escape")
    assert page.evaluate("window.quickChatHidden")
    expect(field).to_have_value("keep draft")


def test_quick_chat_failure_and_long_text_keep_input(ui):
    from playwright.sync_api import expect

    page, _, _ = ui
    url = urlsplit(page.url)
    page.goto(f"{url.scheme}://{url.netloc}/tests/voice/quick-chat-entry/")
    field = page.get_by_role("textbox", name="Message", exact=True)
    # Ordinary long input follows the same send hook; never truncate to OSC's display length.
    text = "長い文章です。" * 600
    field.fill(text)
    page.evaluate("window.fail = true")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_role("alert")).to_be_visible()
    expect(field).to_have_value(text)
    assert page.evaluate("window.sent") == []
    page.evaluate("window.fail = false")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(field).to_have_value("")
    sent = page.evaluate("window.sent")
    assert len(sent) == 1
    assert json.loads(base64.b64decode(sent[0]["data"]))["message"] == text


def test_unconfirmed_send_stays_pending_and_keeps_draft(ui):
    from playwright.sync_api import expect

    page, _, _ = ui
    url = urlsplit(page.url)
    page.goto(f"{url.scheme}://{url.netloc}/tests/voice/quick-chat-entry/")
    field = page.get_by_role("textbox", name="Message", exact=True)
    field.fill("Waiting draft")
    page.clock.install()
    page.evaluate("window.hold = true")
    field.press("Enter")
    page.clock.fast_forward(5100)
    expect(page.get_by_role("alert")).to_contain_text("confirmation")
    expect(page.get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(field).to_have_value("Waiting draft")
    field.press("Enter")
    assert page.evaluate("window.sent") == []
    page.evaluate("window.release()")
    expect(field).to_have_value("")
    assert len(page.evaluate("window.sent")) == 1
