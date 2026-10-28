"""Real overlay history/render entry points; replace glyph drawing only."""

from PIL import Image

from models.overlay.overlay_image import OverlayImage


def renderer(monkeypatch):
    overlay = OverlayImage()
    drawn = []

    def textbox(kind, text, language, translations, *args, **kwargs):
        drawn.append((kind, text, translations))
        return Image.new("RGBA", (100, 20), (255, 255, 255, 255))

    monkeypatch.setattr(overlay, "createTextboxLargeLog", textbox)
    return overlay, drawn


def caption(
    overlay,
    identity=("mic", "session", "u"),
    revision=1,
    state="partial",
    text="hello",
    translations=None,
):
    return overlay.createOverlayImageLargeLog(
        "send" if identity[0] == "mic" else "receive",
        text,
        "English",
        translations or [],
        ["Japanese"],
        caption_id=identity,
        caption_state=state,
        caption_revision=revision,
    )


def test_partial_history_is_replaced_and_final_translation_updates_same_entry(
    monkeypatch,
):
    overlay, drawn = renderer(monkeypatch)
    caption(overlay)
    caption(overlay, revision=2, text="hello world")
    assert overlay.message_log == []
    assert len(overlay.caption_pending) == 1
    assert drawn[-1][1] == "hello world"
    caption(overlay, revision=3, state="final", text="final")
    assert len(overlay.message_log) == 1 and not overlay.caption_pending
    caption(
        overlay, revision=4, state="translated", text="final", translations=["訳文"]
    )
    assert len(overlay.message_log) == 1
    assert overlay.message_log[0]["translation"] == ["訳文"]
    assert caption(overlay, revision=99, text="late") is None
    assert caption(overlay, revision=3, state="final") is None


def test_stop_discards_only_its_namespace_pending_and_never_revives(monkeypatch):
    overlay, drawn = renderer(monkeypatch)
    caption(overlay)
    caption(overlay, identity=("speaker", "other", "u"))
    image = overlay.discardCaptionNamespace("mic", "session")
    assert image.size[0] > 1
    assert list(overlay.caption_pending) == [("speaker", "other", "u")]
    assert caption(overlay, revision=99) is None
    image = overlay.discardCaptionNamespace("speaker", "other")
    assert not overlay.message_log and not overlay.caption_pending
    assert image.getextrema()[3] == (0, 0)


def test_legacy_append_and_evicted_final_cannot_reappear_as_translation(monkeypatch):
    overlay, drawn = renderer(monkeypatch)
    caption(overlay, state="final")
    for i in range(7):
        overlay.createOverlayImageLargeLog("send", str(i), "English")
    assert len(overlay.message_log) == 5
    assert [row["message"] for row in overlay.message_log] == [
        str(i) for i in range(2, 7)
    ]
    assert (
        caption(overlay, state="translated", revision=2, translations=["late"]) is None
    )
    assert len(overlay.message_log) == 5


def test_render_revision_marks_old_images_before_publication(monkeypatch):
    overlay, drawn = renderer(monkeypatch)
    first = caption(overlay)
    second = caption(overlay, revision=2)
    assert first.info["vrct_overlay_revision"] < second.info["vrct_overlay_revision"]
    assert overlay.isCurrentLargeLog(second)
    assert not overlay.isCurrentLargeLog(first)
