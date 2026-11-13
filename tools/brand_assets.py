"""Build the README and About page logos and the Tauri app icons from docs/brand.

    uv run --no-project --with pillow --with fonttools python tools/brand_assets.py

Needs rsvg-convert and Noto Sans CJK Bold for the CJK and Hangul labels.
Labels are converted to outlines, so the SVGs render the same without fonts.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTCollection
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / 'docs/brand'
ICONS = ROOT / 'src-tauri/icons'
UI_LOGOS = ROOT / 'src-ui/views/assets/brand'
FONT = Path('/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc')

# Hand-drawn letters on a 64 x 80 cell with an 80-unit advance.
LETTERS = {
    '-': 'M8 33H56V47H8Z',
    'A': 'M24 0H40L64 80H47L42 62H22L17 80H0ZM26 47H38L32 24Z',
    'C': 'M18 0H64V15H24L16 23V57L24 65H64V80H18L0 62V18Z',
    'E': 'M0 0H64V15H16V32H54V47H16V65H64V80H0Z',
    'L': 'M0 0H16V65H64V80H0Z',
    'N': 'M0 0H16L48 51V0H64V80H48L16 29V80H0Z',
    'O': 'M18 0H46L64 18V62L46 80H18L0 62V18ZM24 15L16 23V57L24 65H40L48 57V23L40 15Z',
    'R': 'M0 0H44L60 16V36L47 49L64 80H46L29 50H16V80H0ZM16 14V36H38L44 30V20L38 14Z',
    'S': 'M16 0H64V15H23L16 22V28L23 33H48L64 49V64L48 80H0V65H41L48 58V53L41 48H16L0 32V16Z',
    'T': 'M0 0H64V15H40V80H24V15H0Z',
    'V': 'M0 0H16L32 57L48 0H64L40 80H24Z',
    'X': 'M0 0H18L32 25L46 0H64L41 40L64 80H46L32 55L18 80H0L23 40Z',
}
FEATURES = ('asr', 'tts', 'rvc', 'ocr', 'translate')
LABELS = {
    'en': ('ASR', 'TTS', 'RVC', 'OCR', 'TRANSLATE'),
    'ja': ('音声認識', '音声合成', '声質変換', '文字認識', '翻訳'),
    'ko': ('음성인식', '음성합성', '음성변환', '문자인식', '번역'),
    'zh-Hant': ('語音辨識', '語音合成', '聲音轉換', '文字辨識', '翻譯'),
    'zh-Hans': ('语音识别', '语音合成', '声音转换', '文字识别', '翻译'),
}
FACES = {'ja': 'Noto Sans CJK JP', 'ko': 'Noto Sans CJK KR', 'zh-Hant': 'Noto Sans CJK TC', 'zh-Hans': 'Noto Sans CJK SC'}
DESCRIPTIONS = {
    'en': 'VRCT-VOX: speech recognition, text to speech, voice conversion, screen text reading and translation.',
    'ja': 'VRCT-VOX：音声認識、音声合成、声質変換、文字認識、翻訳。',
    'ko': 'VRCT-VOX: 음성 인식, 음성 합성, 음성 변환, 문자 인식, 번역.',
    'zh-Hant': 'VRCT-VOX：語音辨識、語音合成、聲音轉換、文字辨識、翻譯。',
    'zh-Hans': 'VRCT-VOX：语音识别、语音合成、声音转换、文字识别、翻译。',
}
THEMES = {'dark': ('#F5F5F7', '#B9D8FF'), 'light': ('#13161C', '#174899')}

WIDTH, HEIGHT = 1000, 240
WORD_X, WORD_Y, WORD_SCALE = 264, 44, 1.08
ROW_Y, GLYPH, GAP = 161, 32, 8
LATIN_SCALE, CJK_SIZE = 0.2, 20
ROW_END = WORD_X + (7 * 80 + 64) * WORD_SCALE


def inner(svg):
    """Drawing content of a docs/brand SVG, without its root, title and desc."""
    body = re.search(r'<svg[^>]*>(.*)</svg>', svg, re.DOTALL).group(1)
    return re.sub(r'<(title|desc)[^>]*>.*?</\1>', '', body, flags=re.DOTALL).strip()


def latin(text, x, y, scale, fill):
    paths = ''.join(f'<path transform="translate({i * 80} 0)" d="{LETTERS[c]}"/>' for i, c in enumerate(text))
    return f'<g transform="translate({x:g} {y:g}) scale({scale:g})" fill="{fill}" fill-rule="evenodd">{paths}</g>'


def latin_width(text, scale):
    return ((len(text) - 1) * 80 + 64) * scale


class Cjk:
    def __init__(self, face):
        fonts = TTCollection(str(FONT)).fonts
        self.font = next(f for f in fonts if f['name'].getDebugName(1) == face)
        self.cmap, self.glyphs = self.font.getBestCmap(), self.font.getGlyphSet()
        self.upm = self.font['head'].unitsPerEm

    def text(self, text, x, y, size, fill):
        # The ideographic em box is centered 0.38 em above the baseline.
        scale, baseline = size / self.upm, y + 0.38 * size
        pen = SVGPathPen(self.glyphs)
        for i, char in enumerate(text):
            name = self.cmap[ord(char)]
            self.glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x + i * size, baseline)))
        return f'<path fill="{fill}" d="{pen.getCommands()}"/>'


def logo(lang, theme, glyphs, icon_small):
    ink, accent = THEMES[theme]
    labels = LABELS[lang]
    cjk = Cjk(FACES[lang]) if lang in FACES else None
    widths = [latin_width(t, LATIN_SCALE) if cjk is None else len(t) * CJK_SIZE for t in labels]
    spacing = (ROW_END - WORD_X - sum(GLYPH + GAP + w for w in widths)) / (len(labels) - 1)
    parts, x, middle = [], WORD_X, ROW_Y + GLYPH / 2
    for name, label, width in zip(FEATURES, labels, widths):
        parts.append(f'<g transform="translate({x:g} {ROW_Y}) scale({GLYPH / 24:g})" color="{accent}">{glyphs[name]}</g>')
        if cjk is None:
            parts.append(latin(label, x + GLYPH + GAP, middle - 40 * LATIN_SCALE, LATIN_SCALE, ink))
        else:
            parts.append(cjk.text(label, x + GLYPH + GAP, middle, CJK_SIZE, ink))
        x += GLYPH + GAP + width + spacing
    description = DESCRIPTIONS[lang]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">\n'
            f'<title id="title">VRCT-VOX</title>\n<desc id="desc">{description}</desc>\n'
            f'<g transform="translate(24 24) scale(0.375)">{icon_small}</g>'
            f'{latin("VRCT-VOX", WORD_X, WORD_Y, WORD_SCALE, ink)}{"".join(parts)}\n</svg>\n')


def render(svg, size, out):
    subprocess.run(['rsvg-convert', '-w', str(size), '-h', str(size), '-o', str(out), str(svg)], check=True)
    return Image.open(out).convert('RGBA')


def icons():
    # Below 256 px the small optical version stays legible; the full icon shows all five functions.
    def source(size):
        return BRAND / ('icon.svg' if size >= 256 else 'icon-small.svg')

    with tempfile.TemporaryDirectory() as tmp:
        cache = {}

        def image(size):
            if size not in cache:
                cache[size] = render(source(size), size, Path(tmp) / f'{size}.png')
            return cache[size]

        names = {'32x32.png': 32, '128x128.png': 128, '128x128@2x.png': 256, 'icon.png': 512,
                 'StoreLogo.png': 50, **{f'Square{n}x{n}Logo.png': n for n in (30, 44, 71, 89, 107, 142, 150, 284, 310)}}
        for name, size in names.items():
            image(size).save(ICONS / name, optimize=True)
        ico = [16, 24, 32, 48, 64, 256]
        image(256).save(ICONS / 'icon.ico', sizes=[(s, s) for s in ico], append_images=[image(s) for s in ico[:-1]])
        icns = [16, 32, 64, 128, 256, 512, 1024]
        image(1024).save(ICONS / 'icon.icns', append_images=[image(s) for s in icns[:-1]])


def main():
    glyphs = {name: inner((BRAND / 'glyphs' / f'{name}.svg').read_text()).replace('scale(1.0)', 'scale(1)')
              for name in FEATURES}
    icon_small = inner((BRAND / 'icon-small.svg').read_text())
    UI_LOGOS.mkdir(exist_ok=True)
    for lang in LABELS:
        for theme in THEMES:
            (BRAND / f'logo-{lang}-on-{theme}.svg').write_text(logo(lang, theme, glyphs, icon_small))
        # The app UI is dark only.
        (UI_LOGOS / f'logo-{lang}.svg').write_text(logo(lang, 'dark', glyphs, icon_small))
    (UI_LOGOS / 'icon-small.svg').write_text((BRAND / 'icon-small.svg').read_text())
    icons()


if __name__ == '__main__':
    sys.exit(main())
