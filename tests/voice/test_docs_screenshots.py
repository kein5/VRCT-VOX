"""Screenshots of the production screens for the user documentation (site/).

Not a test: it renders tests/voice/studio-entry with the offline sidecar peer,
like test_studio_ui.py, and writes images. It runs only when asked, through
tools/docs_screenshots.py, so `check` never does it.

The peer answers with sample data (a short conversation, a VRChat that was
found, a catalogue of models), so the pictures show the app in use and carry
nobody's device names.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from ui_details import open_engine_settings

from test_studio_ui import studio, ui  # noqa: F401  (fixtures)

OUTPUT = os.environ.get("VRCT_DOCS_SCREENSHOTS")
pytestmark = pytest.mark.skipif(not OUTPUT, reason="writes documentation screenshots; run tools/docs_screenshots.py")

# File name -> settings page label, per language (locales/*.yml side_menu_labels).
PAGES = {
    "device": {"ja": "デバイス", "en": "Device"},
    "translation": {"ja": "翻訳", "en": "Translation"},
    "transcription": {"ja": "音声認識", "en": "Transcription"},
    "chat-reading": {"ja": "チャット読み取り", "en": "Chat Transcribe"},
    "tts": {"ja": "TTS", "en": "TTS"},
    "rvc": {"ja": "RVC", "en": "RVC"},
    "vr": {"ja": "VR", "en": "VR"},
    "hotkeys": {"ja": "ホットキー", "en": "Hotkeys"},
    "advanced": {"ja": "高度な設定", "en": "Advanced"},
}
# File name -> (settings page, the text to bring to the top of the picture, open the folded setup first).
SECTIONS = {
    "asr-models": ("transcription", {"ja": "ASR + VAD", "en": "ASR + VAD"}, True),
    "desktop-captions": ("vr", {"ja": "デスクトップの字幕オーバーレイ", "en": "Desktop caption overlay"}, False),
}
TITLE = {"ja": "ここから会話を始めましょう", "en": "Your conversation starts here"}
OPEN_SETTINGS = {"ja": "設定を開く", "en": "Open settings"}
BACK = {"ja": "戻る", "en": "Go Back"}
QUICK_SETTINGS = {"ja": "クイック設定", "en": "Quick settings"}
REVIEW = {"ja": "取得内容を確認", "en": "Review download"}
# studio-entry shows a fixture version; the documentation shows the app's own.
FIXTURE_VERSION = "3.6.0-beta.1"
APP_VERSION = json.loads((Path(__file__).resolve().parents[2] / "package.json").read_text())["version"]
# The last line of tests/voice/caption-overlay-entry/entry.jsx, to know its captions are drawn.
CAPTION_SAMPLE = "Thank you. I'm looking forward to it!"
# Where downloaded models go on Linux (site/*/guide/models.md).
SAVE_TO = "~/.config/vrct-vox/downloaded_models"
# The log stamps each row with the time it arrived; a fixed clock keeps the pictures the same between runs.
CLOCK = datetime(2026, 1, 10, 21, 30)
# studio-entry sets "your language" to Japanese and the target to English in both display languages.
CONVERSATION = [
    ("/run/transcription_send_mic_message", "こんばんは！このワールドは初めて来ました。", "Good evening! This is my first time in this world."),
    ("/run/transcription_receive_speaker_message", "Welcome! Let me show you around.", "ようこそ！案内しますね。"),
    ("/run/transcription_send_mic_message", "ありがとうございます。お願いします！", "Thank you. Yes, please!"),
]
ANSWERS = {
    "/get/data/vrchat_osc_presence": "found",
    "/get/data/selectable_translation_engines": ["CTranslate2"],
    "/get/data/selected_translation_engines": {"1": "CTranslate2", "2": "CTranslate2", "3": "CTranslate2"},
    "/get/data/selectable_transcription_engines": ["Google", "Whisper"],
    "/get/data/selected_transcription_engine": "Whisper",
}


def answer(peer):
    """Let the peer answer the sample data above, after what the studio fixture already answers."""
    studio_answers = peer.extra

    def extra(endpoint, data):
        if endpoint in ANSWERS:
            push(peer, endpoint, ANSWERS[endpoint])
            return True
        return studio_answers(endpoint, data)

    peer.extra = extra


def push(peer, endpoint, result):
    peer.replies.append(dict(endpoint=endpoint, result=result, status=200))


def save(page, path, replace=()):
    """Write the picture. `replace` lists (shown text, text for the picture) pairs beyond the version."""
    page.evaluate(
        "async () => { await Promise.all(document.getAnimations()"
        ".filter(a => a.effect.getTiming().iterations !== Infinity)"
        ".map(a => a.finished.catch(() => {}))); }"
    )
    page.evaluate(
        """pairs => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            for (let node = walker.nextNode(); node; node = walker.nextNode())
                for (const [shown, wanted] of pairs)
                    if (node.nodeValue.includes(shown)) node.nodeValue = node.nodeValue.replaceAll(shown, wanted);
        }""",
        [[FIXTURE_VERSION, APP_VERSION], *replace],
    )
    from PIL import Image

    png = path.with_suffix(".png")
    page.screenshot(path=str(png))
    Image.open(png).save(path, "WEBP", quality=82, method=6)
    png.unlink()


def main_page_in_use(page, peer, lang):
    """Translation on, an engine chosen, and a short conversation in the log."""
    for endpoint in ("/get/data/selectable_translation_engines", "/get/data/selected_translation_engines"):
        push(peer, endpoint, ANSWERS[endpoint])
    push(peer, "/set/enable/translation", True)
    # A VRChat on this PC with OSC on: messages are sent and mute sync is available.
    push(peer, "/get/data/send_message_to_vrc", True)
    push(peer, "/run/enable_osc_query", {"data": True, "disabled_functions": []})
    for endpoint, original, translation in CONVERSATION:
        push(peer, endpoint, {
            "original": {"message": original, "transliteration": []},
            "translations": [{"message": translation, "transliteration": []}],
        })
    page.get_by_text(CONVERSATION[-1][2], exact=True).wait_for()


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_docs_screenshots(studio, tmp_path, lang):  # noqa: F811
    page, peer = studio
    answer(peer)
    out = Path(OUTPUT) / lang
    out.mkdir(parents=True, exist_ok=True)
    origin = urlsplit(page.url)
    page.clock.set_fixed_time(CLOCK)
    page.goto(f"{origin.scheme}://{origin.netloc}/tests/voice/studio-entry/?lang={lang}")
    page.get_by_role("heading", name=TITLE[lang]).wait_for()
    main_page_in_use(page, peer, lang)
    save(page, out / "main.webp")

    page.get_by_role("button", name=QUICK_SETTINGS[lang]).click()
    page.wait_for_timeout(600)
    save(page, out / "quick-settings.webp")
    page.keyboard.press("Escape")

    # The desktop caption section asks the Tauri shell whether its window exists (Windows only).
    page.evaluate(
        "window.__TAURI_INTERNALS__ = { invoke: async command => command === 'caption_overlay_supported' ? true : null }"
    )
    page.get_by_role("button", name=OPEN_SETTINGS[lang], exact=True).click()
    for name, labels in PAGES.items():
        page.get_by_role("button", name=labels[lang], exact=True).click()
        page.wait_for_timeout(300)
        save(page, out / f"{name}.webp")
    for name, (parent, labels, folded) in SECTIONS.items():
        page.get_by_role("button", name=PAGES[parent][lang], exact=True).click()
        page.wait_for_timeout(300)
        if folded:
            open_engine_settings(page)
        heading = page.get_by_text(labels[lang], exact=True).first
        heading.wait_for()
        heading.evaluate("node => node.scrollIntoView({ block: 'start' })")
        page.wait_for_timeout(300)
        save(page, out / f"{name}.webp")

    page.get_by_role("button", name=PAGES["tts"][lang], exact=True).click()
    open_engine_settings(page)
    page.get_by_role("button", name=REVIEW[lang], exact=True).first.click()
    page.get_by_role("dialog").wait_for()
    page.wait_for_timeout(300)
    # The dialog names the folder it saves to. Here that is this run's temporary folder, under the
    # home of whoever made the pictures; show the place a Linux install uses instead.
    models = str(tmp_path / "models")
    folder = page.get_by_role("dialog").get_by_text(models).first.inner_text()
    shown = SAVE_TO + folder[len(models):].replace("\\", "/")
    save(page, out / "model-consent.webp", replace=[[folder, shown]])
    page.keyboard.press("Escape")

    # The desktop captions themselves, over a stand-in scene (tests/voice/caption-overlay-entry).
    # The page does not depend on the display language; each language keeps its own copy.
    page.goto(f"{origin.scheme}://{origin.netloc}/tests/voice/caption-overlay-entry/")
    page.get_by_text(CAPTION_SAMPLE, exact=True).wait_for()
    save(page, out / "captions-on-screen.webp")
