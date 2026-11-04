"""Subtitle raster regressions using the shipped fonts, without VR or a display."""

from unittest.mock import patch
import builtins
import importlib.util

from PIL import Image
import pytest

from models.overlay import overlay_fonts
from models.overlay.overlay_fonts import TextLine, graphemes, system_emoji_paths
from models.overlay.overlay_image import (
    MAX_SUBTITLE_HEIGHT,
    MAX_SUBTITLE_LINES,
    MAX_SUBTITLE_PIXELS,
    MAX_SUBTITLE_WIDTH,
    OverlayImage,
)


@pytest.fixture(autouse=True, params=["regex", "stdlib"])
def segmentation_backend(request, monkeypatch):
    if request.param == "stdlib":
        monkeypatch.setattr(overlay_fonts, "_regex", None)
    elif overlay_fonts._regex is None:
        pytest.skip("Optional regex is not installed; the stdlib cases still run")


@pytest.fixture
def overlay():
    return OverlayImage()


def render(overlay, kind, text, ruby, **kwargs):
    tokens = [{"orig": text, "hira": text, "hepburn": "reading"}] if ruby else []
    if kind == "large":
        return overlay.createOverlayImageLargeLog(
            "receive", text, "Japanese", transliteration_message=tokens, **kwargs)
    return overlay.createOverlayImageSmallLog(
        text, "Japanese", transliteration_message=tokens, **kwargs)


def assert_bounded(image):
    assert 0 < image.width <= MAX_SUBTITLE_WIDTH
    assert 0 < image.height <= MAX_SUBTITLE_HEIGHT
    assert image.width * image.height <= MAX_SUBTITLE_PIXELS
    assert len(image.info["subtitle_rows"]) <= MAX_SUBTITLE_LINES


@pytest.fixture
def measured_draws(monkeypatch):
    """Check every actual run's bounds before it reaches the Pillow canvas."""
    original = TextLine.draw
    calls = []

    def checked(line, image, x, y, color):
        assert 0 <= x <= image.width
        assert x + line.width <= image.width
        assert 0 <= y <= image.height
        assert y + line.height <= image.height
        calls.append((line.width, line.height))
        return original(line, image, x, y, color)

    monkeypatch.setattr(TextLine, "draw", checked)
    return calls


@pytest.mark.parametrize("kind", ["large", "small"])
@pytest.mark.parametrize("ruby", [False, True])
def test_audit_multiline_zero_division(overlay, measured_draws, kind, ruby):
    image = render(overlay, kind, "あ\n" * 20 + "あ", ruby)
    assert_bounded(image)
    assert measured_draws


@pytest.mark.parametrize("kind", ["large", "small"])
@pytest.mark.parametrize("ruby", [False, True])
def test_mixed_width_text_fits_canvas(overlay, measured_draws, kind, ruby):
    image = render(overlay, kind, "漢" * 40 + "i" * 120, ruby)
    assert_bounded(image)
    assert not image.info["subtitle_clipped"]
    assert len(measured_draws) > 1


@pytest.mark.parametrize("text", ["あ" * 100_000, "あ\n" * 1000 + "あ"])
@pytest.mark.parametrize("kind", ["large", "small"])
@pytest.mark.parametrize("ruby", [False, True])
def test_huge_inputs_are_bounded_before_allocation(overlay, kind, ruby, text):
    allocations = []
    new = Image.new

    def checked(mode, size, *args, **kwargs):
        width, height = size
        assert 0 < width <= MAX_SUBTITLE_WIDTH
        assert 0 < height <= MAX_SUBTITLE_HEIGHT
        assert width * height <= MAX_SUBTITLE_PIXELS
        allocations.append(size)
        return new(mode, size, *args, **kwargs)

    with patch.object(Image, "new", side_effect=checked):
        image = render(overlay, kind, text, ruby)
    assert_bounded(image)
    assert image.info["subtitle_clipped"]
    assert len(allocations) < 20  # No raster per input line/token.
    # The final line visibly contains the omission marker, not just metadata.
    top, bottom = image.info["subtitle_rows"][-1]
    padding = 25 if kind == "large" else 50
    region = image.crop((padding, top + padding, image.width - padding, bottom + padding))
    assert any(pixel[:3] == (223, 223, 223) for pixel in region.get_flattened_data())


@pytest.mark.parametrize("text", [None, "", " \t  ", "\n\n", "\u200b\u200d\ufeff", "😀",
                                 "👨‍👩‍👧", "👍🏽", "e\u0301か\u3099", "\u0301", "🇯🇵1️⃣"])
@pytest.mark.parametrize("kind", ["large", "small"])
@pytest.mark.parametrize("ruby", [False, True])
def test_empty_invisible_and_grapheme_inputs(overlay, measured_draws, kind, ruby, text):
    image = render(overlay, kind, text, ruby)
    assert_bounded(image)


def test_explicit_lines_and_latin_words(overlay):
    fonts = overlay._fonts("Japanese", 30)
    lines, clipped = overlay._wrap("one two\n\nthree", fonts, fonts.layout("one two").width)
    assert lines == ["one two", "", "three"]
    assert not clipped
    lines, clipped = overlay._wrap("one two", fonts, fonts.layout("one t").width)
    assert lines == ["one ", "two"]
    assert not clipped


@pytest.mark.parametrize("cluster", ["👨‍👩‍👧", "👍🏽", "e\u0301", "か\u3099", "🇯🇵", "1️⃣"])
def test_oversized_tokens_split_only_at_graphemes(overlay, cluster):
    fonts = overlay._fonts("Japanese", 30)
    text = cluster * 12
    lines, clipped = overlay._wrap(text, fonts, fonts.layout(cluster * 2).width + 1)
    assert not clipped
    assert "".join(lines) == text
    assert all(part == cluster for line in lines for part in graphemes(line))
    assert all(fonts.layout(line).width <= fonts.layout(cluster * 2).width + 1 for line in lines)


@pytest.mark.parametrize("kind", ["large", "small"])
def test_oversized_ruby_readings_and_missing_transliteration_lists(overlay, measured_draws, kind):
    text = "漢" * 40 + "i" * 120
    readings = [[{"orig": text, "hira": "あ" * 160, "hepburn": "longword" * 100}]]
    image = render(overlay, kind, "短い文", False, translation=[text], target_language=["Japanese"],
                   transliteration_translation=readings)
    assert_bounded(image)
    image = render(overlay, kind, "", False, translation=["翻訳だけ"], target_language=["Japanese"])
    assert_bounded(image)
    assert measured_draws  # Translations also render when ruby lists are absent.


@pytest.mark.parametrize("kind", ["large", "small"])
def test_translation_and_history_composition_share_one_budget(overlay, kind):
    calls = []
    original = overlay._draw_row

    def counted(*args):
        calls.append(1)
        return original(*args)

    with patch.object(overlay, "_draw_row", side_effect=counted):
        image = render(overlay, kind, "文", False, translation=["訳文"] * 1000,
                       target_language=["Japanese"] * 1000)
    assert_bounded(image)
    assert image.info["subtitle_clipped"]
    assert len(calls) < 100  # Remaining translations are never rendered.
    if kind == "large":
        overlay.message_log.clear()
        for _ in range(5):
            image = render(overlay, kind, "行\n" * 10, True)
        assert_bounded(image)
        assert image.info["subtitle_clipped"]


@pytest.mark.parametrize("size", [10, 20, 30, 46, 92])
def test_system_emoji_fallback_and_combined_run_bounds(overlay, size):
    fonts = overlay._fonts("Japanese", size)
    assert not fonts.primary.supports("😀")  # Actual bundled JP font.
    if not system_emoji_paths():
        pytest.skip("No locally installed system emoji font; missing-glyph box is expected")
    face = fonts.face_for("😀")
    if face is fonts.primary:
        pytest.skip("Installed emoji fonts cannot be rendered by this Pillow/FreeType build")
    assert face.path in system_emoji_paths()
    assert face.supports("😀")
    line = fonts.layout("漢😀👨‍👩‍👧e\u0301")
    assert any(run[0] is face for run in line.runs)
    canvas = Image.new("RGBA", (line.width + 100, line.height + 100))
    line.draw(canvas, 50, 50, (223, 223, 223))
    left, top, right, bottom = canvas.getbbox()
    assert 50 <= left < right <= 50 + line.width
    assert 50 <= top < bottom <= 50 + line.height


def test_no_system_fallback_preserves_missing_box(overlay, monkeypatch):
    monkeypatch.setattr("models.overlay.overlay_fonts.system_emoji_paths", lambda: ())
    fonts = overlay._fonts("Japanese", 30)
    assert fonts.face_for("😀") is fonts.primary
    image = render(overlay, "large", "😀", False)
    assert_bounded(image)


@pytest.mark.parametrize("text,family", [("한", "NotoSansKR-Regular.ttf"), ("龘", "NotoSansSC-Regular.ttf")])
def test_other_bundled_noto_fonts_precede_system_fallback(overlay, monkeypatch, text, family):
    monkeypatch.setattr("models.overlay.overlay_fonts.system_emoji_paths", lambda: ())
    fonts = overlay._fonts("Japanese", 30)
    assert not fonts.primary.supports(text)
    assert fonts.face_for(text).path.endswith(family)
    assert fonts.face_for(text).supports(text)


@pytest.mark.parametrize("dimensions", [(0, 20), (100, 0), (4097, 10), (10, 2049), (4096, 2048)])
def test_invalid_final_texture_is_rejected_before_allocation(overlay, dimensions):
    with patch.object(Image, "new", side_effect=AssertionError("must validate first")):
        with pytest.raises(ValueError, match="raster budget"):
            overlay._new_image(*dimensions)


def test_pathological_combining_cluster_is_visibly_clipped(overlay, measured_draws):
    for text in ("e" + "\u0301" * 100_000, "\u200b" * 100_000):
        image = render(overlay, "large", text, False)
        assert_bounded(image)
        assert image.info["subtitle_clipped"]


def test_ruby_tokens_cannot_split_message_graphemes(overlay):
    text = "e\u0301👨‍👩‍👧"
    tokens = [{"orig": char, "hira": char} for char in text]
    rows, clipped = overlay._ruby_rows(text, tokens, "Japanese", 30, 0.5, 4, 0,
                                       (223, 223, 223), 960, "left")
    assert not clipped
    originals = [cell[0] for row in rows for cell in row["cells"]]
    drawn = [run[1] for line in originals for run in line.runs]
    assert "".join(drawn) == text
    assert [part for run in drawn for part in graphemes(run)] == list(graphemes(text))


@pytest.mark.parametrize("clusters", [
    [], ["a", "b", "c"], ["e\u0301", "か\u3099"], ["\u0301\u0308", "a"],
    ["क\u093f", "a\u20dd"], ["👨‍👩‍👧", "👍🏽", "🇯🇵", "1️⃣"],
    ["🇯🇵", "🇺🇸", "🇬"], ["🇯", "a", "🇵"], ["👍🏽", "👍🏽"],
    ["a\ufe00", "✈\ufe0e", "✈\ufe0f", "漢\U000e0100", "漢\U000e01ef"],
    ["🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f", "!"],
    ["a", "\r\n", "b", "\r", "c", "\n", "\u0301"],
])
def test_segmentation_matches_expected_sequences_with_either_backend(clusters):
    assert list(graphemes("".join(clusters))) == clusters


def test_missing_regex_import_uses_stdlib_without_retrying(monkeypatch):
    real_import = builtins.__import__
    attempts = []

    def without_regex(name, *args, **kwargs):
        if name == "regex":
            attempts.append(name)
            raise ModuleNotFoundError("regex intentionally unavailable")
        return real_import(name, *args, **kwargs)

    spec = importlib.util.spec_from_file_location("overlay_fonts_without_regex", overlay_fonts.__file__)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as isolated:
        isolated.setattr(builtins, "__import__", without_regex)
        spec.loader.exec_module(module)
        assert module._regex is None
        for _ in range(2):
            assert list(module.graphemes("e\u0301👨‍👩‍👧👍🏽🇯🇵1️⃣")) == ["e\u0301", "👨‍👩‍👧", "👍🏽", "🇯🇵", "1️⃣"]
    assert attempts == ["regex"]
