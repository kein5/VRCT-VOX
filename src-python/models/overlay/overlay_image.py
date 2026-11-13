from os import path as os_path
from datetime import datetime
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from typing import Tuple, List, Optional
from PIL import Image, ImageDraw, ImageFont
from itertools import zip_longest
from math import isfinite
from .overlay_fonts import FontSet, bounded_text, graphemes, word_tokens, MAX_LINE_CODEPOINTS, MAX_TEXT_CODEPOINTS

# Limits include all message/translation/history rows, ruby and outer padding.
# See docs/spec/overlay-subtitle-rendering.md. RGBA is at most 16 MiB per raster.
MAX_SUBTITLE_LINES = 24
MAX_SUBTITLE_WIDTH = 4096
MAX_SUBTITLE_HEIGHT = 2048
MAX_SUBTITLE_PIXELS = 4_194_304
SUBTITLE_PADDING_RESERVE = 100


class OverlayImage:
    LANGUAGES = {
        "Default": "NotoSansJP-Regular.ttf",
        "Japanese": "NotoSansJP-Regular.ttf",
        "Korean": "NotoSansKR-Regular.ttf",
        "Chinese Simplified": "NotoSansSC-Regular.ttf",
        "Chinese Traditional": "NotoSansTC-Regular.ttf",
    }

    def __init__(self, root_path: Optional[str] = None) -> None:
        """Overlay image helper.

        Args:
            root_path: optional project root to resolve bundled fonts. If omitted,
                defaults to repository `fonts` directory.
        """
        self.message_log: List[dict] = []
        self.caption_pending = OrderedDict()
        self._caption_latest = OrderedDict()
        self.log_lock = RLock()
        self._large_revision = 0
        self._large_owner = object()
        # PyInstallerでビルドされた場合のパス
        if  root_path and os_path.exists(os_path.join(root_path, "_internal", "fonts")):
            self.root_path = os_path.join(root_path, "_internal", "fonts")
        # src-pythonフォルダから直接実行している場合のパス
        elif os_path.exists(os_path.join(os_path.dirname(__file__), "models", "overlay", "fonts")):
            self.root_path = os_path.join(os_path.dirname(__file__), "models", "overlay", "fonts")
        # overlayフォルダから直接実行している場合のパス
        elif os_path.exists(os_path.join(os_path.dirname(__file__), "fonts")):
            self.root_path = os_path.join(os_path.dirname(__file__), "fonts")
        else:
            raise FileNotFoundError("Font directory not found.")
        # Simple in-memory font cache to avoid repeated truetype loading cost.
        self._font_cache = {}
        self._font_sets = {}

    @staticmethod
    def validateTextureSize(width, height):
        if (not 0 < width <= MAX_SUBTITLE_WIDTH or not 0 < height <= MAX_SUBTITLE_HEIGHT
                or width * height > MAX_SUBTITLE_PIXELS):
            raise ValueError("subtitle texture exceeds raster budget")

    @staticmethod
    def _content_height(width):
        # Reserve the largest existing outer margin before allocating any text.
        return min(MAX_SUBTITLE_HEIGHT, MAX_SUBTITLE_PIXELS // (width + SUBTITLE_PADDING_RESERVE)) - SUBTITLE_PADDING_RESERVE

    def _new_image(self, width, height, color=(0, 0, 0, 0)):
        self.validateTextureSize(width, height)
        return Image.new("RGBA", (width, height), color)

    def _fonts(self, language, size):
        family = self.LANGUAGES.get(language, self.LANGUAGES["Default"])
        # UI sizes are fixed; bound optional ruby scale before opening a font.
        size = max(1, min(128, int(size)))
        key = (family, size)
        if key not in self._font_sets:
            if len(self._font_sets) >= 32:
                self._font_sets.pop(next(iter(self._font_sets)))
            self._font_sets[key] = FontSet(self.root_path, self.LANGUAGES.values(), family, size)
        return self._font_sets[key]

    def _wrap(self, text, fonts, width):
        text, clipped = bounded_text(text)
        lines = []
        existing_lines = text.split("\n")
        for line_index, existing in enumerate(existing_lines):
            current = ""
            for token in word_tokens(existing):
                candidate = current + token
                if len(candidate) <= MAX_LINE_CODEPOINTS and fonts.layout(candidate).width <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                    current = ""
                if len(lines) >= MAX_SUBTITLE_LINES:
                    return lines, True
                # A long Latin word, ruby reading or indivisible grapheme must
                # never bypass the measured-width check.
                for cluster in graphemes(token):
                    candidate = current + cluster
                    if len(candidate) > MAX_LINE_CODEPOINTS or fonts.layout(candidate).width > width:
                        if current:
                            lines.append(current)
                        if len(lines) >= MAX_SUBTITLE_LINES:
                            return lines, True
                        current = cluster
                        if fonts.layout(cluster).width > width:
                            return lines, True  # Cannot split a grapheme safely.
                    else:
                        current = candidate
            lines.append(current)
            if len(lines) >= MAX_SUBTITLE_LINES:
                return lines, clipped or line_index < len(existing_lines) - 1
        return lines, clipped

    @staticmethod
    def _row(cells, color, align, padding=10, ruby_spacing=4, original_spacing=0, extra=0):
        romaji_height = max((cell[2].height for cell in cells if cell[2]), default=0)
        hira_height = max((cell[1].height for cell in cells if cell[1]), default=0)
        orig_height = max((cell[0].height for cell in cells), default=1)
        ruby_height = romaji_height + hira_height + (ruby_spacing if romaji_height and hira_height else 0)
        return dict(cells=cells, color=color, align=align, padding=padding,
                    romaji_height=romaji_height, hira_height=hira_height,
                    ruby_spacing=ruby_spacing, original_spacing=original_spacing,
                    height=padding * 2 + ruby_height + original_spacing + orig_height + extra,
                    width=sum(cell[3] for cell in cells))

    def _plain_rows(self, text, language, font_size, color, width, align, padding=5, extra=0):
        fonts = self._fonts(language, font_size)
        lines, clipped = self._wrap(text, fonts, width)
        rows = []
        for line in lines:
            layout = fonts.layout(line)
            rows.append(self._row([(layout, None, None, layout.width)], color, align, padding, extra=extra))
        return rows, clipped

    def _ellipsis_row(self, width):
        size = 92 if width > 1000 else 30
        return self._plain_rows("…", "Default", size, (223, 223, 223), width, "center")[0][0]

    def _render_rows(self, rows, width, clipped=False):
        limit = self._content_height(width)
        selected = []
        height = 0
        for row in rows:
            if len(selected) >= MAX_SUBTITLE_LINES or height + row["height"] > limit:
                clipped = True
                break
            selected.append(row)
            height += row["height"]
        if clipped:
            marker = self._ellipsis_row(width)
            while selected and (len(selected) >= MAX_SUBTITLE_LINES or height + marker["height"] > limit):
                height -= selected.pop()["height"]
            selected.append(marker)
            height += marker["height"]
        image = self._new_image(width, max(1, height))
        bounds = []
        y = 0
        for row in selected:
            self._draw_row(image, row, y)
            bounds.append((y, y + row["height"]))
            y += row["height"]
        image.info["subtitle_rows"] = bounds
        image.info["subtitle_clipped"] = clipped
        return image

    @staticmethod
    def _draw_row(image, row, y):
        width = row["width"]
        x = 0 if row["align"] == "left" else image.width - width
        if row["align"] == "center":
            x //= 2
        for orig, hira, romaji, cell_width in row["cells"]:
            top = y + row["padding"]
            if row["romaji_height"]:
                if romaji:
                    romaji.draw(image, x + (cell_width - romaji.width) / 2, top, row["color"])
                top += row["romaji_height"] + (row["ruby_spacing"] if row["hira_height"] else 0)
            if row["hira_height"]:
                if hira:
                    hira.draw(image, x + (cell_width - hira.width) / 2, top, row["color"])
                top += row["hira_height"]
            orig.draw(image, x + (cell_width - orig.width) / 2, top + row["original_spacing"], row["color"])
            x += cell_width

    def concatenateImagesVertically(self, img1: Image, img2: Image, margin: int = 0) -> Image:
        if img1.info.get("subtitle_clipped"):
            return img1
        total_height = img1.height + img2.height + margin
        rows1 = img1.info.get("subtitle_rows", [(0, img1.height)])
        rows2 = [(a + img1.height + margin, b + img1.height + margin)
                 for a, b in img2.info.get("subtitle_rows", [(0, img2.height)])]
        rows = rows1 + rows2
        clipped = len(rows) > MAX_SUBTITLE_LINES or total_height > self._content_height(img1.width)
        marker = None
        if clipped:
            marker = self._ellipsis_row(img1.width)
            rows = rows[:MAX_SUBTITLE_LINES - 1]
            while rows and rows[-1][1] + marker["height"] > self._content_height(img1.width):
                rows.pop()
            total_height = (rows[-1][1] if rows else 0) + marker["height"]
        dst = self._new_image(img1.width, total_height)
        dst.paste(img1, (0, 0))
        dst.paste(img2, (0, img1.height + margin))
        if marker:
            y = total_height - marker["height"]
            ImageDraw.Draw(dst).rectangle((0, y, dst.width, dst.height), fill=(0, 0, 0, 0))
            self._draw_row(dst, marker, y)
            rows.append((y, total_height))
        dst.info["subtitle_rows"] = rows
        dst.info["subtitle_clipped"] = clipped or img2.info.get("subtitle_clipped", False)
        return dst

    def _combine_images(self, images, margin=0):
        result = None
        for image in images:
            result = image if result is None else self.concatenateImagesVertically(result, image, margin)
            if result.info.get("subtitle_clipped"):
                break
        return result if result is not None else self._new_image(1, 1)

    def addImageMargin(self, image: Image, top: int, right: int, bottom: int, left: int, color: Tuple[int, int, int, int]) -> Image:
        result = self._new_image(image.width + right + left, image.height + top + bottom, color)
        result.paste(image, (left, top))
        result.info.update(image.info)
        return result

    @staticmethod
    def getUiSizeSmallLog() -> dict:
        return {
            "width": 3840,
            "height": 92,
            "font_size": 92,
        }

    @staticmethod
    def getUiColorSmallLog() -> dict:
        colors = {
            "background_color": (41, 42, 45),
            "background_outline_color": (41, 42, 45),
            "text_color": (223, 223, 223)
        }
        return colors

    def _get_font(self, font_family: str, size: int) -> ImageFont.FreeTypeFont:
        font_path = os_path.join(self.root_path, font_family)
        key = (font_path, size)
        if key not in self._font_cache:
            self._font_cache[key] = ImageFont.truetype(font_path, size)
        return self._font_cache[key]

    def createTextboxSmallLog(self, text: str, language: str, text_color: Tuple[int, int, int], base_width: int, base_height: int, font_size: int) -> Image:
        rows, clipped = self._plain_rows(text, language, font_size, text_color, int(base_width * 0.9), "center", padding=10)
        # Retain the small subtitle's generous single-block vertical padding.
        if rows:
            rows[0]["padding"] += font_size // 2
            rows[0]["height"] += font_size // 2
            rows[-1]["height"] += font_size - font_size // 2
        return self._render_rows(rows, base_width, clipped)

    def renderRubyBlock(self, transliteration: List[dict], language: str, base_width: int, base_font_size: int, ruby_font_scale: float, ruby_line_spacing: int, text_color: Tuple[int, int, int]) -> Optional[Image.Image]:
        size = self._ruby_size(base_font_size, ruby_font_scale)
        rows = []
        clipped = False
        for key in ("hepburn", "hira"):
            # Bound the fallback path as well as the per-token renderer.
            parts = []
            for token in transliteration[:MAX_SUBTITLE_LINES]:
                part, cut = bounded_text(token.get(key, ""))
                parts.append(part)
                clipped |= cut
            text = " ".join(parts)
            if text:
                part, cut = self._plain_rows(text, language, size, text_color, int(base_width * 0.9), "center")
                rows.extend(part)
                clipped |= cut
        clipped |= len(transliteration) > MAX_SUBTITLE_LINES
        return self._render_rows(rows, base_width, clipped) if rows else None

    @staticmethod
    def _ruby_size(font_size, scale):
        return max(1, min(128, int(font_size * scale))) if isfinite(scale) else max(1, font_size // 2)

    def _ruby_rows(self, message, transliteration, language, font_size, scale, spacing, original_spacing, color, width, align):
        message, clipped = bounded_text(message)
        orig_font = self._fonts(language, font_size)
        ruby_font = self._fonts(language, self._ruby_size(font_size, scale))
        spacing = max(0, min(128, int(spacing)))
        limit = int(width * 0.9)
        rows = []
        cells = []
        cursor = 0
        boundaries = {0}
        end = 0
        for cluster in graphemes(message):
            end += len(cluster)
            boundaries.add(end)

        def flush():
            nonlocal cells
            rows.append(self._row(cells or [(orig_font.layout(""), None, None, 0)], color, align,
                                  ruby_spacing=spacing, original_spacing=original_spacing))
            cells = []

        def pieces():
            nonlocal cursor
            for token in transliteration[:MAX_TEXT_CODEPOINTS]:
                original = token.get("orig", "")
                if not original:
                    continue
                index = message.find(original, cursor)
                if index < 0 or index not in boundaries or index + len(original) not in boundaries:
                    continue
                if index > cursor:
                    yield message[cursor:index], "", ""
                yield original, token.get("hira", ""), token.get("hepburn", "")
                cursor = index + len(original)
            if cursor < len(message):
                yield message[cursor:], "", ""

        for original, hira, romaji in pieces():
            # Each component wraps independently when one ruby token is wider
            # than a line. Do not invent character-to-reading correspondence.
            orig_parts, cut = self._wrap(original, orig_font, limit)
            hira_parts, cut_h = self._wrap(hira, ruby_font, limit)
            romaji_parts, cut_r = self._wrap(romaji, ruby_font, limit)
            clipped |= cut or cut_h or cut_r
            for i, (o, h, r) in enumerate(zip_longest(orig_parts, hira_parts, romaji_parts, fillvalue="")):
                if i:
                    flush()
                layouts = (orig_font.layout(o), ruby_font.layout(h) if h else None, ruby_font.layout(r) if r else None)
                cell_width = max(layout.width for layout in layouts if layout)
                if cells and sum(cell[3] for cell in cells) + cell_width > limit:
                    flush()
                cells.append((*layouts, cell_width))
                if len(rows) >= MAX_SUBTITLE_LINES:
                    return rows, True
            if cut or cut_h or cut_r:
                break
        if cells:
            flush()
        return rows, clipped

    def createTextboxSmallLogWithRubyTokens(self, message: str, transliteration: List[dict], language: str, text_color: Tuple[int, int, int], base_width: int, font_size: int, ruby_font_scale: float, ruby_line_spacing: int, ruby_original_spacing: int) -> Image:
        if not message or not transliteration:
            return self.createTextboxSmallLog(message, language, text_color, base_width, self.getUiSizeSmallLog()["height"], font_size)
        rows, clipped = self._ruby_rows(message, transliteration, language, font_size, ruby_font_scale,
                                        ruby_line_spacing, ruby_original_spacing, text_color, base_width, "center")
        return self._render_rows(rows, base_width, clipped)

    def createOverlayImageSmallLog(self, message: str, your_language: str, translation: List[str] = [], target_language: List[str] = [], transliteration_message: List[dict] = [], transliteration_translation: List[List[dict]] = [], ruby_font_scale: float = 0.5, ruby_line_spacing: int = 4) -> Image:
        # UI設定を取得
        ui_size = self.getUiSizeSmallLog()
        width, height, font_size = ui_size["width"], ui_size["height"], ui_size["font_size"]

        ui_colors = self.getUiColorSmallLog()
        text_color = ui_colors["text_color"]
        background_color = ui_colors["background_color"]
        background_outline_color = ui_colors["background_outline_color"]

        def textboxes():
            if translation and target_language:
                if message:
                    yield self.createTextboxSmallLog(message, your_language, text_color, width, height, font_size)
                for i, (trans, lang) in enumerate(zip(translation, target_language)):
                    tokens = transliteration_translation[i] if i < len(transliteration_translation) else []
                    yield self.createTextboxSmallLogWithRubyTokens(
                        trans, tokens, lang, text_color, width, font_size, ruby_font_scale, ruby_line_spacing, 2)
            else:
                yield self.createTextboxSmallLogWithRubyTokens(
                    message, transliteration_message, your_language, text_color, width, font_size,
                    ruby_font_scale, ruby_line_spacing, 2)

        img = self._combine_images(textboxes())

        # 画像周囲にUIパディングを追加して、文字が端に張り付かないようにする
        ui_outer_padding = 50
        img = self.addImageMargin(img, ui_outer_padding, ui_outer_padding, ui_outer_padding, ui_outer_padding, (0, 0, 0, 0))

        # 角丸背景を作成
        background = self._new_image(*img.size)
        draw = ImageDraw.Draw(background)
        draw.rounded_rectangle([(0, 0), img.size], radius=50, fill=background_color, outline=background_outline_color, width=5)

        # 背景とテキストを合成
        info = img.info.copy()
        img = Image.alpha_composite(background, img)
        img.info.update(info)
        self.validateTextureSize(*img.size)
        return img

    @staticmethod
    def getUiSizeLargeLog() -> dict:
        return {
            "width": 960,
            "font_size_large": 30,
            "font_size_small": 20,
            "margin": 25,
            "radius": 25,
            "padding": 10,
            "clause_margin": 20,
        }

    @staticmethod
    def getUiColorLargeLog() -> dict:
        return {
            "background_color": (41, 42, 45),
            "background_outline_color": (41, 42, 45),
            "text_color_large": (223, 223, 223),
            "text_color_small": (190, 190, 190),
            "text_color_send": (97, 151, 180),
            "text_color_receive": (168, 97, 180),
            "text_color_time": (120, 120, 120)
        }

    def createTextImageLargeLog(self, message_type: str, size: str, text: str, language: str) -> Image:
        ui_size = self.getUiSizeLargeLog()
        font_size = ui_size["font_size_large"] if size == "large" else ui_size["font_size_small"]
        text_color = self.getUiColorLargeLog()[f"text_color_{size}"]
        align = "left" if message_type == "receive" else "right"
        rows, clipped = self._plain_rows(text, language, font_size, text_color, ui_size["width"], align)
        return self._render_rows(rows, ui_size["width"], clipped)

    def createTextboxLargeLogWithRubyTokens(self, message_type: str, size: str, message: str, transliteration: List[dict], language: str, ruby_font_scale: float, ruby_line_spacing: int) -> Image:
        if not message or not transliteration:
            return self.createTextImageLargeLog(message_type, size, message, language)
        ui_size = self.getUiSizeLargeLog()
        font_size = ui_size["font_size_large"] if size == "large" else ui_size["font_size_small"]
        color = self.getUiColorLargeLog()[f"text_color_{size}"]
        align = "left" if message_type == "receive" else "right"
        rows, clipped = self._ruby_rows(message, transliteration, language, font_size, ruby_font_scale,
                                        ruby_line_spacing, 0, color, ui_size["width"], align)
        return self._render_rows(rows, ui_size["width"], clipped)

    def createTextImageMessageType(self, message_type: str, date_time: str) -> Image:
        ui_size = self.getUiSizeLargeLog()
        font_size = ui_size["font_size_small"]
        ui_padding = ui_size["padding"]

        ui_color = self.getUiColorLargeLog()
        text_color = ui_color[f"text_color_{message_type}"]
        text_color_time = ui_color["text_color_time"]

        anchor = "lm" if message_type == "receive" else "rm"
        text = "Receive" if message_type == "receive" else "Send"

        date_time = date_time or ""
        img = self._new_image(1, 1)
        draw = ImageDraw.Draw(img)

        font = self._get_font(self.LANGUAGES["Default"], font_size)

        text_height = font_size + ui_padding
        text_width = draw.textlength(date_time, font)
        character_width = text_width // max(1, len(date_time))
        img = self._new_image(ui_size["width"], text_height)
        draw = ImageDraw.Draw(img)
        text_y = text_height // 2
        text_time_x = 0 if message_type == "receive" else ui_size["width"] - (text_width + character_width)
        text_x = (text_width + character_width) if message_type == "receive" else ui_size["width"]
        draw.text((text_time_x, text_y), date_time, text_color_time, anchor=anchor, stroke_width=0, font=font)
        draw.text((text_x, text_y), text, text_color, anchor=anchor, stroke_width=0, font=font)
        return img

    def createTextboxLargeLog(self, message_type: str, message: Optional[str] = None, your_language: Optional[str] = None, translation: List[str] = [], target_language: List[str] = [], date_time: Optional[str] = None, transliteration_message: Optional[List[dict]] = None, transliteration_translation: Optional[List[List[dict]]] = None, ruby_font_scale: float = 0.5, ruby_line_spacing: int = 4) -> Image:
        def textboxes():
            yield self.createTextImageMessageType(message_type, date_time)
            if translation and target_language:
                if message is not None:
                    yield self.createTextImageLargeLog(message_type, "small", message, your_language)
                readings = transliteration_translation or []
                for i, (trans, lang) in enumerate(zip(translation, target_language)):
                    tokens = readings[i] if i < len(readings) else []
                    yield self.createTextboxLargeLogWithRubyTokens(
                        message_type, "large", trans, tokens, lang, ruby_font_scale, ruby_line_spacing)
            else:
                yield self.createTextboxLargeLogWithRubyTokens(
                    message_type, "large", message, transliteration_message, your_language, ruby_font_scale, ruby_line_spacing)

        return self._combine_images(textboxes())

    def _rememberCaption(self, identity, revision, state):
        self._caption_latest[identity] = (revision, state)
        self._caption_latest.move_to_end(identity)
        while len(self._caption_latest) > 256:
            self._caption_latest.popitem(last=False)

    def isCurrentLargeLog(self, image):
        return (image.info.get("vrct_overlay_owner") is not self._large_owner
                or image.info.get("vrct_overlay_revision") == self._large_revision)

    def _renderLargeLogVersion(self, **kwargs):
        image = self._renderLargeLog(**kwargs)
        self._large_revision += 1
        image.info["vrct_overlay_revision"] = self._large_revision
        image.info["vrct_overlay_owner"] = self._large_owner
        return image

    def discardCaptionNamespace(self, source, namespace):
        with self.log_lock:
            for identity in tuple(self.caption_pending):
                if identity[:2] == (source, namespace):
                    self.caption_pending.pop(identity)
                    self._rememberCaption(identity, self._caption_latest[identity][0], "discarded")
            return self._renderLargeLogVersion()

    def checkpointCaptionState(self):
        """Caller holds log_lock across render and the publication decision."""
        return deepcopy((self.message_log, self.caption_pending, self._caption_latest))

    def restoreCaptionState(self, checkpoint):
        self.message_log, self.caption_pending, self._caption_latest = checkpoint
        self._large_revision += 1  # Invalidate the rejected image as well.

    def rejectCaptionUpdate(self, checkpoint, identity, revision):
        self.restoreCaptionState(checkpoint)
        # Preserve any earlier published final, but never leave an expired
        # partial available for an unrelated source's later render.
        self.caption_pending.pop(identity, None)
        previous = self._caption_latest.get(identity, (0, None))
        self._rememberCaption(identity, max(revision, previous[0]), "discarded")

    def createOverlayImageLargeLog(self, message_type: str, message: Optional[str] = None, your_language: Optional[str] = None, translation: List[str] = [], target_language: List[str] = [], transliteration_message: List[dict] = [], transliteration_translation: List[List[dict]] = [], ruby_font_scale: float = 0.5, ruby_line_spacing: int = 4, *, caption_id=None, caption_state="final", caption_revision=0) -> Image:
        with self.log_lock:
            record = {
                "message_type": message_type, "message": message, "your_language": your_language,
                "translation": translation, "target_language": target_language,
                "transliteration_message": transliteration_message,
                "transliteration_translation": transliteration_translation,
                "datetime": datetime.now().strftime("%H:%M"),
            }
            if caption_id is None:
                self.message_log.append(record)
            else:
                if (not isinstance(caption_id, tuple) or len(caption_id) != 3
                        or caption_id[0] not in ("mic", "speaker")
                        or not all(isinstance(value, str) and value for value in caption_id)
                        or caption_state not in ("partial", "final", "translated", "discarded")
                        or type(caption_revision) is not int or caption_revision < 1):
                    raise ValueError("invalid_overlay_caption")
                previous = self._caption_latest.get(caption_id)
                existing = next((row for row in self.message_log if row.get("caption_id") == caption_id), None)
                if previous and (caption_revision <= previous[0] or previous[1] in ("discarded", "translated")
                                 or (previous[1] == "final" and (caption_state != "translated" or existing is None))):
                    return None
                record["caption_id"] = caption_id
                pending = self.caption_pending.get(caption_id)
                if existing is not None or pending is not None:
                    record["datetime"] = (existing if existing is not None else pending)["datetime"]
                self._rememberCaption(caption_id, caption_revision, caption_state)
                if caption_state == "partial":
                    if caption_id not in self.caption_pending and len(self.caption_pending) >= 16:
                        oldest, _ = self.caption_pending.popitem(last=False)
                        self._rememberCaption(oldest, self._caption_latest[oldest][0], "discarded")
                    self.caption_pending[caption_id] = record
                else:
                    self.caption_pending.pop(caption_id, None)
                    if caption_state != "discarded":
                        if existing is not None:
                            existing.update(record)
                        else:
                            self.message_log.append(record)
            self.message_log = self.message_log[-5:]
            return self._renderLargeLogVersion(ruby_font_scale=ruby_font_scale, ruby_line_spacing=ruby_line_spacing)

    def _renderLargeLog(self, ruby_font_scale=0.5, ruby_line_spacing=4):
        logs = self.message_log + list(self.caption_pending.values())
        ui_color = self.getUiColorLargeLog()
        background_color = ui_color["background_color"]
        background_outline_color = ui_color["background_outline_color"]

        ui_size = self.getUiSizeLargeLog()
        ui_margin = ui_size["margin"]
        ui_radius = ui_size["radius"]
        ui_clause_margin = ui_size["clause_margin"]

        imgs = (
            self.createTextboxLargeLog(
                log["message_type"],
                log["message"],
                log["your_language"],
                log["translation"],
                log["target_language"],
                log["datetime"],
                transliteration_message=log.get("transliteration_message", [{}]),
                transliteration_translation=log.get("transliteration_translation", [{}]),
                ruby_font_scale=ruby_font_scale,
                ruby_line_spacing=ruby_line_spacing,
            ) for log in logs
        )

        if not logs:
            return self._new_image(1, 1)
        img = self._combine_images(imgs, ui_clause_margin)
        img = self.addImageMargin(img, ui_margin, ui_margin, ui_margin, ui_margin, (0, 0, 0, 0))

        width, height = img.size
        background = self._new_image(width, height)
        draw = ImageDraw.Draw(background)
        draw.rounded_rectangle([(0, 0), (width, height)], radius=ui_radius, fill=background_color, outline=background_outline_color, width=5)
        info = img.info.copy()
        img = Image.alpha_composite(background, img)
        img.info.update(info)
        self.validateTextureSize(*img.size)
        return img

if __name__ == "__main__":
    overlay = OverlayImage()
    # Basic small log test (with translation list form)
    img = overlay.createOverlayImageSmallLog("Hello, World!", "English", ["こんにちは、世界！"], ["Japanese"], [], [[]])
    img.save("overlay_small.png")

    # Ruby small log test (Japanese original with transliteration tokens)
    ruby_tokens = [
        {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
        {"orig": "る", "hira": "る", "hepburn": "ru"},
    ]
    # Ruby on original + ruby on translation example
    translation_tokens = [
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ],
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ],
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ]
    ]
    img_ruby = overlay.createOverlayImageSmallLog(
        "慮る",
        "Japanese",
        ["慮る", "慮る", "慮る"],
        ["Japanese", "Japanese", "Japanese"],
        transliteration_message=ruby_tokens,
        transliteration_translation=translation_tokens,
        ruby_font_scale=0.5,
        ruby_line_spacing=4,
    )
    img_ruby.save("overlay_small_ruby.png")

    # Large log tests (adjusted to pass translation/target_language as lists)
    img = overlay.createOverlayImageLargeLog("send", "Hello, World!", "English", ["こんにちは、世界！"], ["Japanese"], transliteration_message=[], transliteration_translation=[])
    img = overlay.createOverlayImageLargeLog("receive", "こんにちは、世界！", "Japanese", ["Hello, World!"], ["English"], transliteration_message=[
        {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
        {"orig": "る", "hira": "る", "hepburn": "ru"},
    ], transliteration_translation=[
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ]
    ])
    long_en = "Hello, World!"
    long_jp = "こんにちは、世界！"
    img = overlay.createOverlayImageLargeLog("send", long_en, "English", [long_jp], ["Japanese"], transliteration_message=[
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ], transliteration_translation=[[]])
    img = overlay.createOverlayImageLargeLog("receive", long_jp, "Japanese", [long_en], ["English"], transliteration_message=[], transliteration_translation=[
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ]
    ])
    img = overlay.createOverlayImageLargeLog("send", "Hello, World!", "English", ["こんにちは、世界！"], ["Japanese"], transliteration_message=[
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
    ], transliteration_translation=[[]])

    img = overlay.createOverlayImageLargeLog("receive", "こんにちは、世界！", "Japanese", ["Hello, World!"], ["English"], transliteration_message=[
            {"orig": "こんにちは", "hira": "こんにちは", "hepburn": "konnichiha"},
            {"orig": "世界", "hira": "sekai", "hepburn": "sekai"},
        ], transliteration_translation=[
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ]
    ])
    img = overlay.createOverlayImageLargeLog("send", long_en, "English", [long_jp], ["Japanese"], transliteration_message=[
        {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
        {"orig": "る", "hira": "る", "hepburn": "ru"},
    ], transliteration_translation=[
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ]
    ])
    img = overlay.createOverlayImageLargeLog("receive", long_jp, "Japanese", [long_en, long_en, long_en], ["English", "English", "English"], transliteration_message=[
        {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
        {"orig": "る", "hira": "る", "hepburn": "ru"},
    ], transliteration_translation=[
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ],
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ],
        [
            {"orig": "慮", "hira": "おもんぱか", "hepburn": "omonpaka"},
            {"orig": "る", "hira": "る", "hepburn": "ru"},
        ]
    ])
    img.save("overlay_large.png")

    # Additional tests to reproduce wrapping + ruby behaviour
    # Long message that will force wrapping in small-log width
    long_msg_jp = "これは非常に長いテキストです。表示幅を超えると折り返しが発生します。"*2
    # Create simple transliteration tokens (one token per short chunk)
    tokens = []
    for i, part in enumerate(["これは", "非常に", "長い", "テキスト", "です", "表示幅", "を", "超える", "と", "折り返し", "が", "発生", "します", "これは", "非常に", "長い", "テキスト", "です", "表示幅", "を", "超える", "と", "折り返し", "が", "発生", "します"]):
        tokens.append({"orig": part, "hira": part, "hepburn": "aaaaa"})

    print("Generating test_overlay_long_small.png (small log, expected block ruby fallback)")
    img_long_small = overlay.createOverlayImageSmallLog(long_msg_jp, "Japanese", [], [], transliteration_message=tokens, transliteration_translation=[[]], ruby_font_scale=0.5, ruby_line_spacing=4)
    img_long_small.save("test_overlay_long_small.png")

    print("Generating test_overlay_long_large.png (large log, already falls back for multiline)")
    img_long_large = overlay.createOverlayImageLargeLog("receive", long_msg_jp, "Japanese", [], [], transliteration_message=tokens, transliteration_translation=[[]])
    img_long_large.save("test_overlay_long_large.png")

    print("Generating test_overlay_long_large.png (large log, already falls back for multiline)")
    img_long_large = overlay.createOverlayImageLargeLog("receive", long_msg_jp, "Japanese", [], [], transliteration_message=tokens, transliteration_translation=[[]])
    img_long_large.save("test_overlay_long_large.png")

    print("Generating test_overlay_long_large.png (large log, already falls back for multiline)")
    img_long_large = overlay.createOverlayImageLargeLog("receive", long_msg_jp, "Japanese", [], [], transliteration_message=tokens, transliteration_translation=[[]])
    img_long_large.save("test_overlay_long_large.png")

    print("Generating test_overlay_long_large.png (large log, already falls back for multiline)")
    img_long_large = overlay.createOverlayImageLargeLog("receive", long_msg_jp, "Japanese", [long_msg_jp, long_msg_jp, long_msg_jp], ["Japanese", "Japanese", "Japanese"], transliteration_message=tokens, transliteration_translation=[tokens, tokens, tokens])
    img_long_large.save("test_overlay_long_large.png")
    print("Done. Check test_overlay_long_small.png and test_overlay_long_large.png for expected layout.")
