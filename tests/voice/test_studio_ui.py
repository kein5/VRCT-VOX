"""Whole production screens: keyboard navigation, viewport fit and model consent."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from ui_details import open_engine_settings

from test_model_downloads_ui import ui as ui

# Shared pytest fixtures are intentionally re-exported for discovery.
__all__ = ["ui"]

pytestmark = pytest.mark.skipif(
    os.environ.get("VRCT_TEST_STUDIO_UI") != "1", reason="opt-in whole-app browser test"
)


@pytest.fixture
def studio(ui):
    page, peer, reply, _ = ui
    from models.tts.settings import VoiceSettings
    from models.voice_conversion.settings import DirectSettings

    responses = {
        "/get/data/voice_settings": VoiceSettings().to_dict(),
        "/get/data/voice_output_devices": {"devices": [], "error": None},
        "/get/data/direct_voice_sources": {"sources": [], "error": None},
        "/get/data/direct_voice_state": {
            "observation_id": "1",
            "mode": "off",
            "active": False,
            "generation": 0,
            "settings": DirectSettings().to_dict(),
        },
    }

    def extra(endpoint, _data):
        if endpoint not in responses:
            return False
        reply(endpoint, responses[endpoint])
        return True

    peer.extra = extra
    origin = urlsplit(page.url)
    page.set_viewport_size({"width": 1200, "height": 850})
    page.goto(f"{origin.scheme}://{origin.netloc}/tests/voice/studio-entry/")
    page.get_by_role("heading", name="ここから会話を始めましょう").wait_for()
    return page, peer


def screenshot(page, name):
    page.evaluate(
        "async () => { await Promise.all(document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))); }"
    )
    if directory := os.environ.get("VRCT_STUDIO_SCREENSHOTS"):
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination / f"{name}.png"))


def test_navigation_keyboard_and_all_settings(studio):
    from playwright.sync_api import expect

    page, _ = studio
    screenshot(page, "main-ja")
    settings = page.get_by_role("button", name="設定を開く", exact=True)
    settings.focus()
    page.keyboard.press("Enter")
    device = page.get_by_role("button", name="デバイス", exact=True)
    expect(device).to_be_visible()
    screenshot(page, "device-ja")
    for label in (
        "デザイン",
        "翻訳",
        "音声認識",
        "チャット読み取り",
        "VR",
        "その他",
        "ホットキー",
        "TTS",
        "RVC",
        "高度な設定",
        "アップデート",
        "About VRCT-VOX",
    ):
        tab = page.get_by_role("button", name=label, exact=True)
        tab.focus()
        page.keyboard.press("Enter")
        expect(tab).to_have_attribute("aria-current", "page")
        if label in ("TTS", "RVC", "ホットキー", "デザイン", "About VRCT-VOX"):
            screenshot(page, f"settings-{label}-ja")
    page.get_by_role("button", name="戻る", exact=True).click()
    expect(settings).to_be_visible()
    expect(settings).to_be_focused()
    expect(device).not_to_be_visible()


def test_small_window_and_reduced_motion(studio):
    from playwright.sync_api import expect

    page, _ = studio
    page.emulate_media(reduced_motion="reduce")
    for width, height in ((860, 620), (640, 480), (400, 300)):
        page.set_viewport_size({"width": width, "height": height})
        field = page.get_by_role("textbox", name="メッセージ", exact=True)
        expect(field).to_be_visible()
        bounds = field.bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width + 1
        screenshot(page, f"main-{width}")
    page.get_by_role("button", name="設定を開く", exact=True).click()
    page.get_by_role("button", name="TTS", exact=True).click()
    page.mouse.move(399, 290)
    screenshot(page, "tts-400")
    expect(page.get_by_role("button", name="戻る", exact=True)).to_be_in_viewport()


def test_model_warning_in_styled_screen_keeps_explicit_consent(studio):
    from playwright.sync_api import expect

    page, peer = studio
    page.get_by_role("button", name="設定を開く", exact=True).click()
    page.get_by_role("button", name="TTS", exact=True).click()
    open_engine_settings(page)
    page.get_by_role("button", name="取得内容を確認", exact=True).first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(
        dialog.get_by_role("button", name="同意してダウンロード", exact=True)
    ).to_be_disabled()
    screenshot(page, "model-consent-ja")
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    assert not any(ep == "/run/start_model_download" for ep, _ in peer.sent)


def test_settings_checkboxes_are_reachable_from_the_keyboard(studio):
    from playwright.sync_api import expect

    page, _ = studio
    page.get_by_role("button", name="設定を開く", exact=True).click()
    page.get_by_role("button", name="その他", exact=True).click()
    # The drawn box replaces the native one, but the input stays in the tab order.
    box = page.get_by_role("checkbox").first
    expect(box).to_be_attached()
    box.focus()
    expect(box).to_be_focused()


def test_settings_top_bar_stops_speech_and_mutes_without_starting_anything(studio):
    from playwright.sync_api import expect

    page, peer = studio
    page.get_by_role("button", name="設定を開く", exact=True).click()
    page.get_by_role("button", name="翻訳", exact=True).click()
    actions = page.get_by_role("group", name="停止", exact=True)
    stop = actions.get_by_role("button", name="読み上げを停止", exact=True)
    # The studio peer reports no route state: a plain mute, named for TTS output.
    mute = actions.get_by_role("button", name="読み上げをミュート", exact=True)
    expect(mute).not_to_have_attribute("aria-pressed", "true")
    before = len(peer.sent)
    stop.focus()
    page.keyboard.press("Enter")
    mute.focus()
    page.keyboard.press("Enter")
    def requests():
        return [ep for ep, _ in peer.sent[before:] if ep.startswith(("/run/", "/set/"))]

    for _ in range(50):
        if len(requests()) >= 2:
            break
        page.wait_for_timeout(50)
    # Only the stop and mute requests: nothing resumed, started or rerouted.
    assert requests() == ["/run/stop_voice", "/run/mute_voice"]
    expect(stop).to_be_visible()
