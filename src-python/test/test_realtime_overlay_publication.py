"""Actual Model/renderer publication, with an in-memory overlay destination."""

from unittest.mock import MagicMock
from PIL import Image

from model import Model
from models.overlay.overlay_image import OverlayImage


def model_fixture():
    instance = object.__new__(Model)
    instance.ensure_initialized = lambda: None
    instance.overlay_image = OverlayImage()
    instance.overlay_image.createTextboxLargeLog = lambda *a, **kw: Image.new(
        "RGBA", (100, 20), "white"
    )
    instance.overlay = MagicMock()
    return instance


def test_outdated_render_cannot_overwrite_newer_overlay_but_external_preview_can():
    instance = model_fixture()
    first = instance.overlay_image.createOverlayImageLargeLog(
        "send", "first", "English"
    )
    second = instance.overlay_image.createOverlayImageLargeLog(
        "send", "second", "English"
    )
    instance.updateOverlayLargeLog(second)
    instance.updateOverlayLargeLog(first)
    instance.overlay.updateImage.assert_called_once_with(second, "large")
    other = OverlayImage()
    other.createTextboxLargeLog = instance.overlay_image.createTextboxLargeLog
    preview = other.createOverlayImageLargeLog("send", "preview", "English")
    instance.updateOverlayLargeLog(preview)
    assert instance.overlay.updateImage.call_count == 2


def test_caption_guard_after_render_and_stop_cleanup():
    instance = model_fixture()
    current = [True]
    original = instance.overlay_image.createTextboxLargeLog

    def slow(*args, **kwargs):
        current[0] = False
        return original(*args, **kwargs)

    instance.overlay_image.createTextboxLargeLog = slow
    payload = dict(
        source="mic",
        namespace="n",
        item_id="u",
        revision=1,
        state="partial",
        text="pending",
        translations=[],
    )
    instance.publishRealtimeCaptionOverlay(payload, "English", {}, lambda: current[0])
    instance.overlay.updateImage.assert_not_called()
    instance.clearRealtimeCaptionOverlay("mic", "n")
    assert not instance.overlay_image.caption_pending
    instance.overlay.updateImage.assert_called_once()
