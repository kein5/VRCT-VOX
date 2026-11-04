# SteamVR subtitle images

`src-python/models/overlay/overlay_image.py` builds both subtitle textures.
This contract covers subtitle pixels only; message delivery, OSC text and
retained conversation text are unchanged.

## Layout and bounds

Existing explicit newlines are preserved. Lines wrap against measured glyph
bounds and advances, including fallback fonts. Latin words stay together when
they fit; oversized words split at grapheme boundaries. When the optional
`regex` module is importable, its `\X` supplies extended grapheme boundaries.
It is imported once at module load; an `ImportError` selects the standard-library
fallback, without installing or requiring a new dependency.

The fallback groups a base with combining marks (`unicodedata.combining` or
categories Mn, Mc, Me), variation selectors U+FE00–FE0F and U+E0100–E01EF, emoji
modifiers U+1F3FB–1F3FF, ZWJ sequences, regional-indicator pairs and emoji tags
U+E0020–E007F. It keeps CRLF together and separates other controls. This is an
approximation, **not full UAX #29**: for example, it does not implement Hangul
Jamo composition or all Indic conjunct/prepend rules, and it joins non-control
ZWJ sequences more broadly than the Unicode emoji rule. Those scripts can have
different wrapping boundaries when `regex` is absent.

The covered combining marks, flags and emoji ZWJ sequences are never split to
fit a line in either mode. Empty/invisible input produces a
valid transparent text block. A grapheme that cannot fit is replaced by the
omission line along with the remaining text.

The ordinary font sizes, colors, horizontal alignment, small subtitle padding
and per-token ruby order (romaji, hiragana, original) remain. Line height grows
to contain actual ink, including combining marks and fallback emoji. Ruby
tokens wider than the available line are split into grapheme-safe fragments;
each reading wraps independently. These fragments do not claim linguistic
character-to-reading alignment. Original text absent from ruby tokens,
including whitespace/newlines, is rendered without ruby.

Limits apply **before allocation**, to text blocks, concatenation, backgrounds,
outer margins and the final texture:

| Constant | Limit |
| --- | --- |
| `MAX_SUBTITLE_LINES` | 24 logical rows, including timestamp headers and the omission row; one original line with its ruby is one logical row |
| `MAX_SUBTITLE_WIDTH` | 4096 pixels |
| `MAX_SUBTITLE_HEIGHT` | 2048 pixels |
| `MAX_SUBTITLE_PIXELS` | 4,194,304 pixels (16 MiB for one RGBA raster) |
| `SUBTITLE_PADDING_RESERVE` | 100 pixels reserved in both dimensions when budgeting text, enough for the existing small subtitle outer margins |

All limits apply together. Small subtitles retain their 3940px padded width,
so the area limit allows at most 1064px height. Large subtitles retain their
1010px padded width. Their row count normally limits height first. Concatenation
shares the row/pixel budget across the original, translations and large-log
history. The visible prefix ends at a complete row followed by a centered `…`
line when any limit is reached. Rendering stops there; later blocks are not
rasterized. The stored messages are not modified or paginated automatically.
The final dimensions are validated before returning the image. These limits
bound each raster, not the total process RSS or native texture-copy overhead.

To bound measurement and shaping work, `overlay_fonts.py` also limits each
input component to `MAX_TEXT_CODEPOINTS = 8192`, each grapheme to
`MAX_CLUSTER_CODEPOINTS = 128`, and each shaped line to
`MAX_LINE_CODEPOINTS = 512`. A prefix never retains a partial final grapheme.
Input/cluster truncation also displays `…`; the per-line limit wraps intact
graphemes. Ruby font sizes and spacing are capped at 128px. These are display
budgets, not limits on chat input or transmission.

## Local font fallback

Missing glyphs are detected by comparing each character's mask with that font's
missing-glyph mask. A whole grapheme uses the first font covering its visible
characters: the selected bundled Noto font, the other bundled Noto fonts, then
a locally installed emoji font. Shaping controls and variation selectors do not
require a standalone glyph. Adjacent runs share baseline measurement; the same
font and metrics are used for wrapping and drawing.

- Windows searches the Windows and per-user font directories, including
  `seguiemj.ttf` (Segoe UI Emoji).
- Linux searches `/usr/share/fonts`, `/usr/local/share/fonts`,
  `~/.local/share/fonts` and `~/.fonts` for emoji fonts or Symbola. Noto Color
  Emoji's fixed 109px bitmap strike is measured and resized per grapheme to the
  existing subtitle/ruby size. Both the native glyph raster and final texture
  are bounded before allocation.
- If no usable local font covers the whole grapheme, the selected font's
  existing missing-glyph box remains. Color and complex emoji ligature support
  depend on the installed font and Pillow/FreeType shaping support.

No fonts or dependencies are downloaded or bundled by this change. System
fonts are read from the user's installation, not copied into distributions.

## Verification

`src-python/test/test_overlay_image_rendering.py` uses real bundled fonts and
patches `Image.new` to verify allocation requests. It covers multiline Japanese,
mixed-width text, huge input, composition, empty/invisible input, graphemes,
ruby, missing fallback and optional installed emoji fonts. These tests do not
establish headset readability or Windows runtime rendering.
The rendering and allocation tests run with both `regex` and the forced stdlib
path; explicit segmentation cases check identical boundaries for the sequences
listed above. A separate test simulates `regex` failing to import at module load.
