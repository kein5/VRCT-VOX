# VRCT-TTS architecture infographics

Open [the interactive HTML](vrct-architecture-infographic.html) in a browser. It contains four Japanese views and an SVG export button. Saved SVGs are embedded as an offline fallback. The adjacent `.infographic` files are editable AntV DSL sources; `.svg` and `.png` files are rendered exports/previews.

Scope and code references: [current architecture, 2026-10-28](../current-architecture-2026-10-28.md), application HEAD `232b4b79`. Diagrams simplify the Linux managed route. Implemented does not mean accepted on every platform. Seed-VC remains a separate PoC.

Created using the official [AntV infographic-creator skill](https://github.com/antvis/Infographic/blob/main/skills/infographic-creator/SKILL.md) and AntV Infographic **0.2.20**. The HTML references that fixed MIT library from unpkg; no library is added to application dependencies. Icons are inline original SVG paths. Japanese fonts are resolved locally.

Validation: all four views rendered in Chromium without JavaScript errors and each SVG export succeeded. Offline fallback and exports also passed at 1600px and 390px viewport widths. Captured PNGs were visually inspected. These are documentation checks, not new acceptance tests of VRCT-TTS audio.

Local reproduction/evidence (gitignored): `tmp/voice-resume/create_architecture_infographic.py`, `render_architecture_infographic.py`, `antv-assets/manifest.json`, `antv-render-results.json`, `antv-offline-results.json`. External specifications, code snapshots and quote-checked research pages are in `tmp/voice-resume/research/current-architecture/`.
