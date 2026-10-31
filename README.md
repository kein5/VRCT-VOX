# VRCT-VOX

[日本語](/docs/readmes/README.ja.md) · [한국어](/docs/readmes/README.ko.md) · [繁體中文](/docs/readmes/README.zh-Hant.md)

VRCT-VOX is an independent development fork of [VRCT](https://github.com/misyaguziya/VRCT), maintained by [kein5](https://github.com/kein5). **This is not an official VRCT release and is not endorsed by the upstream authors or VRChat.**

The fork adds speech.cpp text-to-speech, optional external Seed-VC/RVC voice conversion, realtime ASR and translated speech. Voice output and OSC text are independently configurable: for example, original microphone audio can accompany translated TTS while original and translated text appear in VRChat chat. Local speech.cpp server profiles can be saved, started and stopped from the GUI. Settings can download fixed Irodori, Qwen3-TTS, Haas-ja (Japanese ASR) and RVC model candidates from Hugging Face after explicit license/size consent. GPU/VRAM guidance helps choose standard or lighter TTS variants; it is not a memory reservation or a compatibility guarantee. Downloaded files are size/SHA-256 checked and applied separately. RVC still requires an external runtime, HuBERT and RMVPE.

## Status and downloads

This project is still under development. Linux native integration has automated and real-model validation; Windows packaging and hardware acceptance are deferred to a Windows PC. Listening quality and physical end-to-end latency are not fully verified. See the [model download and GPU guidance results](/docs/voice-stack/model-downloads-integration-report.md), [TTS latency measurements](/docs/voice-stack/tts-low-latency-report.md) and [RVC validation](/docs/voice-stack/rvc-index-search-report.md) for exact hardware, artifacts and limits.

The fork's distribution destination is **[kein5/VRCT-VOX Releases](https://github.com/kein5/VRCT-VOX/releases)**. An installable, fully accepted release is not promised yet. AUR distribution is being planned; no AUR package has been submitted by this work. Upstream VRCT downloads do not contain these changes. The inherited automatic publisher and built-in updater are disabled while fork packages are validated.

Report fork-specific bugs or request support through **[VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues)**. Include OS, version, reproduction steps and redacted logs. Do not send private voice/model files, tokens or fork-specific support requests to the upstream maintainers.

## Development and documentation

- [Implementation/validation ledger](/docs/voice-stack/completion-ledger.md)
- [Voice licenses and distribution boundaries](/docs/voice-stack/licensing.md)
- [Fork distribution checklist](/docs/voice-stack/fork-distribution-isolation.md)
- [Linux package proposal](/docs/voice-stack/linux-distribution-proposal.md)
- [Linux build pipeline and candidate validation](/docs/voice-stack/linux-build-pipeline.md)
- [AppImage build, launch and validation](/docs/voice-stack/appimage.md)
- [Model downloads and GPU/VRAM guidance](/docs/voice-stack/model-downloads.md)
- [Build and CI guide (Japanese)](/docs/readme_build.md)
- [GUI text-to-speech quick start (Japanese)](/docs/voice-stack/tts-quickstart-ja.md)
- [Publication and upstream contribution policy](/docs/voice-stack/publication-and-upstream.md)
- [Original VRCT documentation](https://misyaguziya.github.io/VRCT-Docs/) — covers the upstream application, not fork-specific voice features.

Python work uses `uv`. The Linux pipeline freezes the backend and produces tar.gz and optional AppImage candidates with speech.cpp; the development sidecar remains separate. See the pipeline guides for build commands, validation and remaining release gates. Do not use the Windows batch build commands on Linux.

## Names and storage

Executables and packages use `vrct-vox` / `VRCT-VOX`, the application ID is `io.github.kein5.vrct-vox`, and Linux keeps configuration, data and cache in `vrct-vox` directories (`~/.config/vrct-vox` and so on). See [names and identifiers](/docs/voice-stack/project-rename.md).

## Telemetry and models

VRCT-VOX disables Aptabase telemetry, including when an old upstream key file exists. User-requested translation services may still send text to their configured providers; disabling telemetry does not make all features offline.

Built distributions exclude **all OCR weights**, including the upstream restricted chat-bubble detector and RapidOCR weights. OCR requiring those weights is unavailable without a separately permitted local setup. The repository retains the original model/license for the development uses its terms permit; a source checkout is not a model-free binary distribution. Do not package the checkout wholesale.

No speech.cpp/RVC/Seed-VC weights or reference recordings are implicitly downloaded or bundled by this fork's voice integration. The existing faster-whisper dependency includes Silero VAD resources, recorded separately for license review. Mia2026 was supplied for local testing only and must never be redistributed. The speech.cpp binary bundle includes its dependency notices; its license is distinct from each model's license.

## License and acknowledgements

Original VRCT code remains under the [MIT License](/LICENSE). Original copyright and attribution notices are retained. The restricted OCR model has its [own terms](/src-python/models/ocr/onnx/LICENSE.en.txt); see [NOTICE](/NOTICE.md). External engines, model weights, and the GPL-marked Seed-VC integration have their own terms. LGPL and GPL components in the builds, where to get their source and how to replace them are listed in [NOTICE](/NOTICE.md#lgpl-and-gpl-components-in-vrct-vox-builds); PyAV, whose wheels bundle the GPL x264/x265 encoders, is not distributed, nor is upstream's `translator_engines` (licensed for official VRCT only), so the Google/Bing/Papago web translators are unavailable. The entire voice stack is not claimed to be MIT.

Thank you to the original VRCT team: **みしゃ / misyaguziya** (main development), **しいな / Shiina_12siy** (UI/UX and localization), **レラ / soumt-r** (technical advice), **どね / done_vrc** (logo), and [all upstream contributors](https://github.com/misyaguziya/VRCT/graphs/contributors). This fork builds on their work.

General bug fixes are being separated from TTS-specific changes for possible upstream contribution. No upstream contact or PR, including drafts, is sent without the repository owner's explicit instruction.

VRChat and its associated properties are trademarks or registered trademarks of VRChat Inc. VRCT-VOX is not affiliated with VRChat Inc.

## Development

Start with `npm run doctor`, install the headless checks with `npm run setup:headless`, and install UI dependencies with `python tools/dev.py setup --scope ui`. Run `npm run check` for developer-tool, Node and lint checks. See the [developer guide](docs/development.md) for voice/backend/Rust checks, explicit browser setup and Cocogitto.

[Release candidate and draft workflow](docs/voice-stack/release-candidates.md) keeps build verification separate from publication.

- [VRCT-VOX integration results](/docs/voice-stack/vox-integration-report.md)
