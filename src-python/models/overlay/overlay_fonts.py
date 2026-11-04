"""Local subtitle fonts, grapheme boundaries and shared run measurement.

No font discovery subprocesses or downloads. Use optional regex segmentation
when available, otherwise a standard-library approximation for subtitle text.
"""

from functools import lru_cache
from math import ceil, floor
from os import environ
from pathlib import Path
from unicodedata import category, combining, name

from PIL import Image, ImageDraw, ImageFont

try:
    import regex as _regex
except ImportError:
    _regex = None


MAX_TEXT_CODEPOINTS = 8192
MAX_CLUSTER_CODEPOINTS = 128
MAX_LINE_CODEPOINTS = 512


def graphemes(text):
    if _regex is not None:
        return (match.group() for match in _regex.finditer(r"\X", text))
    return _stdlib_graphemes(text)


def _stdlib_graphemes(text):
    """Keep common combining/emoji sequences intact; not full UAX #29.

    Slice at boundaries instead of appending characters so even a pathological
    cluster can be handed to bounded_text without quadratic string copying.
    """
    start = 0
    previous = ""
    previous_control = False
    regional_count = 0
    for index, char in enumerate(text):
        code = ord(char)
        char_category = category(char)
        tag = 0xE0020 <= code <= 0xE007F
        extend = (combining(char) or char_category in ("Mn", "Mc", "Me")
                  or 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF
                  or 0x1F3FB <= code <= 0x1F3FF or tag)
        control = char_category in ("Cc", "Cf", "Zl", "Zp") and char != "\u200d" and not tag
        regional = 0x1F1E6 <= code <= 0x1F1FF
        if index:
            if previous == "\r" and char == "\n":
                join = True
            elif previous_control or control:
                join = False
            else:
                join = (extend or char == "\u200d" or previous == "\u200d"
                        or (regional and regional_count % 2 == 1))
            if not join:
                yield text[start:index]
                start = index
        regional_count = regional_count + 1 if regional else 0
        previous = char
        previous_control = control
    if text:
        yield text[start:]


def bounded_text(text):
    text = text or ""
    clipped = len(text) > MAX_TEXT_CODEPOINTS
    prefix = text[:MAX_TEXT_CODEPOINTS]
    clusters = list(graphemes(prefix))
    if clipped and clusters:
        clusters.pop()  # The last cluster may continue beyond the prefix.
    safe = []
    for cluster in clusters:
        if len(cluster) > MAX_CLUSTER_CODEPOINTS:
            clipped = True
            break
        safe.append(cluster)
    text = "".join(safe).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")
    return "".join(c for c in text if c == "\n" or category(c) != "Cc"), clipped


def word_tokens(text):
    word = []
    for cluster in graphemes(text):
        first = cluster[0]
        latin = "LATIN" in name(first, "") or category(first).startswith("N")
        if latin or (word and first in "'-’"):
            word.append(cluster)
        else:
            if word:
                yield "".join(word)
                word = []
            yield cluster
    if word:
        yield "".join(word)


@lru_cache(maxsize=1)
def system_emoji_paths():
    roots = [Path(environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path(environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts",
             Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
             Path.home() / ".local/share/fonts", Path.home() / ".fonts"]
    paths = []
    for root in roots:
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if (path.suffix.lower() in (".ttf", ".otf", ".ttc")
                        and any(part in path.name.lower() for part in ("emoji", "seguiemj", "symbola"))):
                    paths.append(str(path))
    return tuple(paths)


class FontFace:
    def __init__(self, path, size, color=False):
        self.path = path
        self.size = size
        self.color = color
        try:
            self.font = ImageFont.truetype(path, size)
        except OSError:
            if not color:
                raise
            # Noto Color Emoji's CBDT bitmap strike is 109px. Other unsupported
            # local formats are skipped by FontSet; no fonts are installed.
            self.font = ImageFont.truetype(path, 109)
        self.scale = size / self.font.size
        self._coverage = {}
        missing = self.font.getmask("\U0010ffff")
        self._missing = (missing.size, bytes(missing))

    def supports(self, char):
        if category(char) == "Cf" or char in "\ufe0e\ufe0f" or 0xE0100 <= ord(char) <= 0xE01EF:
            return True  # Shaping controls do not need a standalone glyph.
        if char not in self._coverage:
            if len(self._coverage) >= 4096:
                self._coverage.clear()
            mask = self.font.getmask(char)
            self._coverage[char] = (mask.size, bytes(mask)) != self._missing
        return self._coverage[char]

    def metrics(self, text):
        box = self.font.getbbox(text, anchor="ls")
        if self.scale != 1 and not self._safe_bitmap(box):
            # Mark it wider than any subtitle so layout emits the omission row
            # before attempting the native-strike allocation.
            return (0, 0, 4097, self.size), 4097
        return tuple(value * self.scale for value in box), self.font.getlength(text) * self.scale

    @staticmethod
    def _safe_bitmap(box):
        width, height = box[2] - box[0], box[3] - box[1]
        return width <= 4096 and height <= 2048 and width * height <= 4_194_304

    def draw(self, image, text, x, baseline, color):
        if self.scale == 1:
            ImageDraw.Draw(image).text((x, baseline), text, font=self.font,
                                      fill=color, anchor="ls", embedded_color=self.color)
            return
        box = self.font.getbbox(text, anchor="ls")
        width, height = box[2] - box[0], box[3] - box[1]
        if width <= 0 or height <= 0:
            return
        # Bitmap faces are drawn one grapheme at a time. Check the native strike
        # too: a pathological combining sequence must not allocate a huge mask.
        if not self._safe_bitmap(box):
            raise ValueError("subtitle glyph exceeds raster budget")
        glyph = Image.new("RGBA", (width, height))
        ImageDraw.Draw(glyph).text((-box[0], -box[1]), text, font=self.font,
                                  fill=color, anchor="ls", embedded_color=True)
        glyph = glyph.resize((max(1, ceil(width * self.scale)), max(1, ceil(height * self.scale))),
                             Image.Resampling.LANCZOS)
        image.alpha_composite(glyph, (round(x + box[0] * self.scale), round(baseline + box[1] * self.scale)))


class FontSet:
    def __init__(self, root, families, selected, size):
        self.primary = FontFace(str(Path(root) / selected), size)
        self.bundled = [str(Path(root) / family) for family in dict.fromkeys(families) if family != selected]
        self.size = size
        self.faces = {self.primary.path: self.primary}

    def face_for(self, cluster):
        if all(self.primary.supports(c) for c in cluster):
            return self.primary
        for path in (*self.bundled, *system_emoji_paths()):
            if path not in self.faces:
                try:
                    self.faces[path] = FontFace(path, self.size, path not in self.bundled)
                except (OSError, ValueError):
                    self.faces[path] = None
            face = self.faces[path]
            if face and all(face.supports(c) for c in cluster):
                return face
        return self.primary  # Preserve the existing missing-glyph box.

    def layout(self, text):
        runs = []
        for cluster in graphemes(text):
            face = self.face_for(cluster)
            if runs and runs[-1][0] is face and face.scale == 1:
                runs[-1] = (face, runs[-1][1] + cluster)
            else:
                runs.append((face, cluster))
        positioned = []
        cursor = left = right = top = bottom = 0
        for face, run in runs:
            box, advance = face.metrics(run)
            positioned.append((face, run, cursor))
            left, right = min(left, cursor + box[0]), max(right, cursor + box[2], cursor + advance)
            top, bottom = min(top, box[1]), max(bottom, box[3])
            cursor += advance
        return TextLine(positioned, floor(left), ceil(right), floor(top), ceil(bottom), self.size)


class TextLine:
    def __init__(self, runs, left, right, top, bottom, size):
        self.runs = runs
        self.left = left
        self.width = right - left
        self.top = top
        self.height = max(size, bottom - top)
        self.ink_height = bottom - top

    def draw(self, image, x, y, color):
        baseline = y - self.top + (self.height - self.ink_height) // 2
        for face, text, offset in self.runs:
            face.draw(image, text, x - self.left + offset, baseline, color)
