# VRCT-VOX brand assets

"Caption Console": a microphone with caption lines on a blue rounded square. VRCT-VOX does five things, ASR, TTS, RVC, OCR and translation. The large icon and the logos show a glyph for each of them.

| File | Use |
| --- | --- |
| `icon.svg` | App icon from 256 px. The dock shows the TTS, RVC, OCR and translation glyphs. |
| `icon-small.svg` | App icon up to 128 px: the microphone and two caption bars, without the dock. |
| `glyphs/*.svg` | The five function glyphs on a 24-unit grid with a 1.8-unit round stroke. They use `currentColor`. |
| `logo-<lang>-on-dark.svg`, `logo-<lang>-on-light.svg` | README logos in English (`en`), Japanese (`ja`) and Traditional Chinese (`zh-Hant`). They have a transparent background and are switched by `prefers-color-scheme`. |

All lettering is outlined, so the SVGs render the same without fonts. The Latin letters are drawn for this logo. The Japanese and Chinese labels are outlines of Noto Sans CJK Bold (SIL Open Font License 1.1). The SVGs contain no embedded raster images or external references.

## Palette

| Role | Hex |
| --- | --- |
| Icon background | `#2056BC` |
| Icon mark | `#F5F5F7` |
| Caption bars, glyphs on dark | `#B9D8FF` |
| Dock | `#173A7C` |
| Glyphs on light | `#174899` |
| Text on light | `#13161C` |
| Text on dark | `#F5F5F7` |

## Regenerating

After changing `icon.svg`, `icon-small.svg`, the glyphs or the labels, run:

```sh
uv run --no-project --with pillow --with fonttools python tools/brand_assets.py
```

This rewrites the logos and every file in `src-tauri/icons` (PNG, `icon.ico`, `icon.icns`). It needs `rsvg-convert` and `/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc`. The AppImage desktop icon is copied from `src-tauri/icons/128x128@2x.png` at build time.
