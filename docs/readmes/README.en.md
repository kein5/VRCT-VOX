# VRCT-TTS

[日本語](/docs/readmes/README.ja.md) · [한국어](/docs/readmes/README.ko.md) · [繁體中文](/docs/readmes/README.zh-Hant.md)

VRCT-TTS is an independent development fork of [VRCT](https://github.com/misyaguziya/VRCT), maintained by [kein5](https://github.com/kein5). It was previously named `kein5/VRCT.cpp`. **This is not an official VRCT release and is not endorsed by the upstream authors or VRChat.**

The fork adds speech.cpp text-to-speech, optional external Seed-VC/RVC voice conversion, realtime ASR and translated speech. Voice output and OSC text are independently configurable: for example, original microphone audio can accompany translated TTS while original and translated text appear in VRChat chat. Local speech.cpp server profiles can be saved, started and stopped from the GUI. Models remain user supplied.

## Status and downloads

This project is still under development. Linux native integration has automated and real-model validation; Windows packaging and hardware acceptance are deferred to a Windows PC. Listening quality and physical end-to-end latency are not fully verified. See the [completion ledger](/docs/voice-stack/completion-ledger.md) and [owned speech.cpp server report](/docs/voice-stack/owned-speech-servers-report.md) for precise scope.

The fork's distribution destination is **[kein5/VRCT-TTS Releases](https://github.com/kein5/VRCT-TTS/releases)**. An installable, fully accepted release is not promised yet. AUR distribution is being planned; no AUR package has been submitted by this work. Upstream VRCT downloads do not contain these changes. The inherited automatic publisher and built-in updater are disabled while fork packages are validated.

Report fork-specific bugs or request support through **[VRCT-TTS Issues](https://github.com/kein5/VRCT-TTS/issues)**. Include OS, version, reproduction steps and redacted logs. Do not send private voice/model files, tokens or fork-specific support requests to the upstream maintainers.

## Development and documentation

- [Implementation/validation ledger](/docs/voice-stack/completion-ledger.md)
- [Voice licenses and distribution boundaries](/docs/voice-stack/licensing.md)
- [Fork distribution checklist](/docs/voice-stack/fork-distribution-isolation.md)
- [Linux package proposal](/docs/voice-stack/linux-distribution-proposal.md)
- [Publication and upstream contribution policy](/docs/voice-stack/publication-and-upstream.md)
- [Original VRCT documentation](https://misyaguziya.github.io/VRCT-Docs/) — covers the upstream application, not fork-specific voice features.

Python work uses `uv`. See the linked reports for reproducible test commands and opt-in native prerequisites. The current development sidecar still uses the checkout and its environment; it is not a standalone Linux package. Do not use the Windows batch build commands on Linux.

## Telemetry and models

VRCT-TTS disables Aptabase telemetry, including when an old upstream key file exists. User-requested translation services may still send text to their configured providers; disabling telemetry does not make all features offline.

Built distributions exclude **all OCR weights**, including the upstream restricted chat-bubble detector and RapidOCR weights. OCR requiring those weights is unavailable without a separately permitted local setup. The repository retains the original model/license for the development uses its terms permit; a source checkout is not a model-free binary distribution. Do not package the checkout wholesale.

No TTS/ASR/VC weights or reference recordings are implicitly downloaded or bundled by this fork's voice integration. Mia2026 was supplied for local testing only and must never be redistributed. The planned speech.cpp binary bundle includes its dependency notices; its license is distinct from each model's license.

## License and acknowledgements

Original VRCT code remains under the [MIT License](/LICENSE). Original copyright and attribution notices are retained. The restricted OCR model has its [own terms](/src-python/models/ocr/onnx/LICENSE.en.txt); see [NOTICE](/NOTICE.md). External engines, model weights, and the GPL-marked Seed-VC integration have their own terms. A final binary dependency/license audit remains a release requirement; the entire voice stack is not claimed to be MIT.

Thank you to the original VRCT team: **みしゃ / misyaguziya** (main development), **しいな / Shiina_12siy** (UI/UX and localization), **レラ / soumt-r** (technical advice), **どね / done_vrc** (logo), and [all upstream contributors](https://github.com/misyaguziya/VRCT/graphs/contributors). This fork builds on their work.

General bug fixes are being separated from TTS-specific changes for possible upstream contribution. No upstream contact or PR, including drafts, is sent without the repository owner's explicit instruction.

VRChat and its associated properties are trademarks or registered trademarks of VRChat Inc. VRCT-TTS is not affiliated with VRChat Inc.
