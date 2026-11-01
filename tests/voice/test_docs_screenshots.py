"""Screenshots of the production screens for the user documentation (site/).

Not a test: it renders tests/voice/studio-entry with the offline sidecar peer,
like test_studio_ui.py, and writes images. It runs only when asked, through
tools/docs_screenshots.py, so `check` never does it.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

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
TITLE = {"ja": "ここから会話を始めましょう", "en": "Your conversation starts here"}
OPEN_SETTINGS = {"ja": "設定を開く", "en": "Open settings"}
# studio-entry shows a fixture version; the documentation shows the app's own.
FIXTURE_VERSION = "3.6.0-beta.1"
APP_VERSION = json.loads((Path(__file__).resolve().parents[2] / "package.json").read_text())["version"]


def save(page, path):
    page.evaluate(
        "async () => { await Promise.all(document.getAnimations()"
        ".filter(a => a.effect.getTiming().iterations !== Infinity)"
        ".map(a => a.finished.catch(() => {}))); }"
    )
    page.evaluate(
        """([fixture, actual]) => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            for (let node = walker.nextNode(); node; node = walker.nextNode())
                if (node.nodeValue.includes(fixture)) node.nodeValue = node.nodeValue.replaceAll(fixture, actual);
        }""",
        [FIXTURE_VERSION, APP_VERSION],
    )
    from PIL import Image

    png = path.with_suffix(".png")
    page.screenshot(path=str(png))
    Image.open(png).save(path, "WEBP", quality=82, method=6)
    png.unlink()


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_docs_screenshots(studio, lang):  # noqa: F811
    page, _ = studio
    out = Path(OUTPUT) / lang
    out.mkdir(parents=True, exist_ok=True)
    origin = urlsplit(page.url)
    page.goto(f"{origin.scheme}://{origin.netloc}/tests/voice/studio-entry/?lang={lang}")
    page.get_by_role("heading", name=TITLE[lang]).wait_for()
    save(page, out / "main.webp")
    page.get_by_role("button", name=OPEN_SETTINGS[lang], exact=True).click()
    for name, labels in PAGES.items():
        page.get_by_role("button", name=labels[lang], exact=True).click()
        page.wait_for_timeout(300)
        save(page, out / f"{name}.webp")
