"""Actual Model/renderer publication, with an in-memory overlay destination."""

from unittest.mock import MagicMock
from PIL import Image
import pytest

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


@pytest.mark.parametrize("state", ["partial", "final", "translated"])
@pytest.mark.parametrize("later", ["cleanup", "other_source"])
def test_rejected_render_never_reappears_in_later_publication(state, later):
    instance = model_fixture()
    payload = dict(source="mic", namespace="n", item_id="u", revision=1,
                   state="final" if state == "translated" else "partial", text="accepted", translations=[])
    instance.publishRealtimeCaptionOverlay(payload, "English", {}, lambda: True)
    current = [True]
    original = instance.overlay_image.createTextboxLargeLog

    def invalidate(*args, **kwargs):
        current[0] = False
        return original(*args, **kwargs)

    instance.overlay_image.createTextboxLargeLog = invalidate
    instance.overlay.updateImage.reset_mock()
    instance.publishRealtimeCaptionOverlay({**payload, "revision": 2, "state": state,
        "text": "rejected", "translations": [{"message": "rejected translation"}] if state == "translated" else []},
        "English", {}, lambda: current[0])
    instance.overlay.updateImage.assert_not_called()
    drawn = []

    def observe(kind, text, language, translations, *args, **kwargs):
        drawn.append((text, translations))
        return original(kind, text, language, translations, *args, **kwargs)

    instance.overlay_image.createTextboxLargeLog = observe
    if later == "cleanup":
        instance.clearRealtimeCaptionOverlay("mic", "n")
    else:
        instance.publishRealtimeCaptionOverlay({**payload, "source": "speaker", "namespace": "other"},
            "English", {}, lambda: True)
    assert "rejected" not in str(drawn)
    if state == "translated":
        assert ("accepted", []) in drawn  # Keep the earlier valid final.
