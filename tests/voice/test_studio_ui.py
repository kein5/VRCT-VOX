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


# Screenshot file names keep the short names.
SHOT_NAMES = {"テキスト読み上げ（TTS）": "TTS", "ボイスチェンジャー（RVC）": "RVC"}


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
        "音声認識（ASR）",
        "VRChat",
        "VR",
        "ホットキー",
        "テキスト読み上げ（TTS）",
        "ボイスチェンジャー（RVC）",
        "高度な設定",
        "アップデート",
        "VRCT-VOXについて",
    ):
        tab = page.get_by_role("button", name=label, exact=True)
        tab.focus()
        page.keyboard.press("Enter")
        expect(tab).to_have_attribute("aria-current", "page")
        if label in ("テキスト読み上げ（TTS）", "ボイスチェンジャー（RVC）", "ホットキー", "デザイン", "VRCT-VOXについて"):
            screenshot(page, f"settings-{SHOT_NAMES.get(label, label)}-ja")
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
    page.get_by_role("button", name="テキスト読み上げ（TTS）", exact=True).click()
    page.mouse.move(399, 290)
    screenshot(page, "tts-400")
    expect(page.get_by_role("button", name="戻る", exact=True)).to_be_in_viewport()


def test_model_warning_in_styled_screen_keeps_explicit_consent(studio):
    from playwright.sync_api import expect

    page, peer = studio
    page.get_by_role("button", name="設定を開く", exact=True).click()
    page.get_by_role("button", name="テキスト読み上げ（TTS）", exact=True).click()
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
    page.get_by_role("button", name="VRChat", exact=True).click()
    # The drawn box replaces the native one, but the input stays in the tab order.
    box = page.get_by_role("checkbox").first
    expect(box).to_be_attached()
    for _ in range(60):
        page.keyboard.press("Tab")
        if box.evaluate("node => node === document.activeElement"):
            break
    expect(box).to_be_focused()


def test_vr_sample_text_stops_with_settings_and_only_the_button_restarts_it(studio):
    from playwright.sync_api import expect

    page, peer = studio

    def sends():
        return len([ep for ep, _ in peer.sent if ep == "/run/send_text_overlay"])

    settings = page.get_by_role("button", name="設定を開く", exact=True)
    settings.click()
    page.get_by_role("button", name="VR", exact=True).click()
    start = page.get_by_role("button", name="サンプルテキストをOverlayに送信する", exact=True)
    stop = page.get_by_role("button", name="送信を停止", exact=True)
    start.click()
    expect(stop).to_be_visible()
    for _ in range(40):
        if sends():
            break
        page.wait_for_timeout(50)
    assert sends()
    page.get_by_role("button", name="戻る", exact=True).click()
    expect(settings).to_be_visible()
    sent = sends()
    page.wait_for_timeout(1500)
    assert sends() == sent
    settings.click()
    # The VR page was only hidden, so this is the same button: it says start and nothing runs.
    expect(start).to_be_visible()
    expect(stop).to_have_count(0)
    page.wait_for_timeout(1500)
    assert sends() == sent
    start.click()
    expect(stop).to_be_visible()
    stop.click()
    expect(start).to_be_visible()


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


def test_unavailable_translators_say_why_and_stay_out_of_the_tab_order(studio):
    from playwright.sync_api import expect

    page, peer = studio
    peer.replies.append(dict(endpoint="/get/data/selectable_translation_engines", result=["CTranslate2"], status=200))
    opener = page.locator('[role="button"][aria-expanded]').filter(has_text="翻訳エンジン")
    opener.focus()
    page.keyboard.press("Enter")
    group = page.get_by_role("group", name="翻訳エンジン", exact=True)
    available = group.get_by_role("button").filter(has_text="CTranslate2")
    unavailable = group.get_by_role("button", name="Google", exact=True)
    expect(available).to_have_attribute("aria-disabled", "false")
    # The keyboard never lands on an unavailable engine, so the reason is on screen.
    reason = "選べないエンジンは、この言語や現在の設定では使えません。APIキーなどは設定の「翻訳」で確認できます。"
    expect(group.get_by_text(reason, exact=True)).to_be_visible()
    expect(group).to_have_accessible_description(reason)
    expect(unavailable).to_have_accessible_description(reason)
    expect(unavailable).to_have_attribute("aria-disabled", "true")
    screenshot(page, "translator-selector-ja")
    page.keyboard.press("Tab")
    expect(available).to_be_focused()
    page.keyboard.press("Tab")
    assert not group.evaluate("node => node.contains(document.activeElement)")


def test_translation_model_setup_is_folded_with_its_status(studio):
    from playwright.sync_api import expect

    page, _ = studio
    page.get_by_role("button", name="設定を開く", exact=True).click()
    page.get_by_role("button", name="翻訳", exact=True).click()
    setup = page.locator("details[data-setup]")
    expect(setup).to_have_count(1)
    expect(setup.locator("summary")).to_contain_text("モデルと処理デバイス")
    expect(setup).not_to_have_attribute("open", "")
