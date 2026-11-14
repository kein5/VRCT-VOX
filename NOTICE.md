# NOTICE

## Optional voice integration in this fork

VRCT-VOX is an independent fork of VRCT. Original VRCT copyright and MIT
license notices are retained in `LICENSE`. The upstream chat-bubble model was
removed in 0.2.0 (see below); **fork binary distributions exclude all OCR
weights** while retaining their attribution documents.

The fork supports external engines and a fixed speech.cpp binary bundle with
separate third-party notices. Voice recordings and additional TTS/ASR/VC model
weights are not bundled. Mia2026 is validation-only. The Seed-VC integration
contains files marked GPL-3.0-only; engine dependencies and weights have their
own licenses. See [voice licensing](docs/voice-stack/licensing.md) for component
boundaries, original sources, and unresolved binary distribution obligations.
Do not infer the complete stack's license from the main MIT license alone.

Upstream VRCT's `translator_engines` extension (Google, Bing and Papago web
translation) is licensed for official VRCT distributions only. VRCT-VOX does
not include it, so those web translators are unavailable; local CTranslate2
translation, DeepL and the LLM providers remain. The distribution policy
rejects it in any build.

## Removed: VRCT's chat-bubble detection model

Commits up to VRCT-VOX 0.1.0 contain `src-python/models/ocr/onnx/chatbox_yolox_tiny.onnx`,
the chat-bubble detection model of upstream VRCT. It is not covered by the MIT
License: it is licensed under the VRCT Chat-Bubble Detection Model License
Agreement (Copyright (c) 2026 misyaguziya), whose text sits next to it in those
commits and in [upstream VRCT](https://github.com/misyaguziya/VRCT). That
agreement allows a fork to run the model while working on VRCT itself, and not
to ship it in a fork's own release.

VRCT-VOX never shipped or ran the model, and is no longer a fork that works on
VRCT, so the file was removed in 0.2.0. VRCT-VOX's own detector, trained
separately and published under MIT, is downloaded only with the user's consent
(see the OCR section below and `docs/ocr_model_license.md` for the background).

## Third-party OCR model weights (upstream VRCT; not in VRCT-VOX builds)

Upstream VRCT bundles these weights in its own builds. VRCT-VOX builds exclude
them, as stated above; the table is kept for attribution.

| Component | Version | License |
|---|---|---|
| YOLOX `yolox_tiny.pth` (COCO-pretrained base of the model above; not shipped, used only at training time) | 0.1.1rc0 | Apache-2.0 |
| RapidOCR (code and YAML config only; its bundled PP-OCR weights are stripped from builds) | 3.9.2 | Apache-2.0 |
| PaddleOCR PP-OCRv6 small det/rec and PP-OCRv5 mobile script recognisers (official ONNX exports by PaddlePaddle on Hugging Face; not shipped, downloaded only after the user agrees in Config → Chat Transcribe) | pinned revisions in `src-python/models/model_downloads/catalog.py` | Apache-2.0 |

VRCT-VOX's own chat-bubble detector, `vrct_vox_chatbox_yolox_tiny.onnx`, is a
separate model: a YOLOX-Tiny trained from VRCT-VOX's own frames with
`tools/chatbox_lab` from Megvii's COCO weights (Apache-2.0), published under
MIT at [kein5/vrct-vox-chatbox-detector](https://huggingface.co/kein5/vrct-vox-chatbox-detector).
It is not derived from the upstream model or its outputs. It is not shipped either; it is downloaded only after the
user agrees in Config → Chat Transcribe (catalog entry `vrct-vox-chatbox-detector`).

## Downloadable Whisper weights

Whisper weights are not bundled. Config → Transcription shows the model,
provider, MIT license and exact pinned file total before checkbox consent and
Download. The models derive from [OpenAI Whisper](https://github.com/openai/whisper/blob/main/LICENSE)
(MIT); the pinned CTranslate2 conversions come from Systran (tiny through
large-v3), Zoont (large-v3-turbo-int8), and deepdml (large-v3-turbo).
Repositories, revisions, file sizes and SHA-256 are in
`src-python/models/builtin_model_pins.py`.

## Downloadable CTranslate2 translation weights

None of these weights ship with VRCT-VOX. The app downloads the selected one
from Hugging Face into `weights/ctranslate2/`. The license is shown next to
each weight in Config → Translation.

| Weight (setting value) | Downloaded from | Upstream model | License |
|---|---|---|---|
| `m2m100_418M-ct2-int8` (**default**) | `jncraton/m2m100_418M-ct2-int8` | `facebook/m2m100_418M` | MIT |
| `m2m100_1.2B-ct2-int8` | `jncraton/m2m100_1.2B-ct2-int8` | `facebook/m2m100_1.2B` | MIT |
| `nllb-200-distilled-600M-ct2-int8` | `JustFrederik/nllb-200-distilled-600M-ct2-int8` | `facebook/nllb-200-distilled-600M` | CC-BY-NC-4.0 (non-commercial) |
| `nllb-200-distilled-1.3B-ct2-int8` | `OpenNMT/nllb-200-distilled-1.3B-ct2-int8` | `facebook/nllb-200-distilled-1.3B` | CC-BY-NC-4.0 (non-commercial) |
| `nllb-200-3.3B-ct2-int8` | `OpenNMT/nllb-200-3.3B-ct2-int8` | `facebook/nllb-200-3.3B` | CC-BY-NC-4.0 (non-commercial) |

Every built-in acquisition requires checkbox consent to the exact model and
manifest, including an already-selected NLLB model and its pinned
tokenizer files. The backend refuses download requests without that consent or with
an outdated manifest. NLLB-200 review always labels CC-BY-NC-4.0 as
non-commercial; selecting a different NLLB model also requires license
confirmation. Keeping an existing selection does not grant download consent. Earlier versions made
`nllb-200-distilled-600M-ct2-int8` the default. Configurations saved by those
versions keep it, and the app shows a one-time notice about its license.

CTranslate2 tokenizers derive from the upstream models in the table and carry
the same MIT or CC-BY-NC-4.0 terms. Acquisition now uses the tokenizer files
already included in the pinned CTranslate2 conversion repositories, with sizes
and SHA-256 in builtin_model_pins.py. The review total includes these files.
Inference reads only these verified local files; no separate upstream tokenizer
acquisition occurs. Existing Hub caches are retained but are not used for admission.
The changed acquisition manifest requires renewed consent before downloading.
No model files or new third-party dependencies are bundled by this change.

Consent is saved per model and manifest in `LEGACY_MODEL_DOWNLOAD_CONSENTS`.
Startup auto-acquisition requires a matching saved consent in addition to the
auto-download switch; legacy settings have no recorded consent. Existing
files and saved selections are preserved.

This table and the OCR table above cover **model weights** only. Python package
dependencies are listed in `pyproject.toml` (resolved in `uv.lock`) and
carry their own licenses; JavaScript and Rust dependencies are listed in
`package.json` and `src-tauri/Cargo.toml`.

## Windows installer download component

The Windows installer uses NScurl. Its retained notices for NScurl, Brotli,
curl, nghttp2, OpenSSL, zlib and Zstandard are embedded in the setup executable
under `$PLUGINSDIR/licenses/nscurl/` and can be read by extracting the installer
with 7-Zip, even if the application download fails. Both Windows application
ZIPs also include these texts in `_internal/licenses/nscurl/` (the `../nscurl/`
directory relative to the installed copy of this NOTICE).
The retained source copies are in
[`src-tauri/nsis/licenses/nscurl/`](src-tauri/nsis/licenses/nscurl/).

## LGPL and GPL components in VRCT-VOX builds

The frozen backend (`_internal` next to the `vrct-vox-sidecar` executable)
contains the following components under the GNU LGPL or GPL. Each is a
separate shared library, Python extension module or Python source directory,
so you may replace it with your own build of the same component and interface;
the application loads whatever file is present. Their license texts are
included under `_internal/licenses/python/` (Python packages) or alongside the
component.

| Component | Where in the build | License | Corresponding source |
|---|---|---|---|
| libsoxr, statically built into the `soxr` 1.1.0 extension module | `_internal/soxr/` | LGPL-2.1-or-later | [soxr 1.1.0 source distribution](https://pypi.org/project/soxr/1.1.0/#files) (contains libsoxr), [python-soxr](https://github.com/dofuuz/python-soxr) |
| FFmpeg libraries (libavcodec, libavformat, libavutil, libswresample, libswscale) shipped with `opencv-python-headless` 4.10.0.84 | Linux: `_internal/opencv_python_headless.libs/`; Windows: `_internal/cv2/opencv_videoio_ffmpeg*.dll` | LGPL-2.1-or-later | [FFmpeg](https://ffmpeg.org/download.html); build scripts and version in [opencv-python 84](https://github.com/opencv/opencv-python/tree/84) |
| libquadmath and libgfortran (GCC runtime) shipped with `opencv-python-headless` on Linux | `_internal/opencv_python_headless.libs/` | libquadmath: LGPL-2.1-or-later; libgfortran: GPL-3.0-or-later with the GCC Runtime Library Exception 3.1 | [GCC](https://gcc.gnu.org/) |
| `zeroconf` 0.152.0 (Python) | `_internal/zeroconf/` (source files, outside the PYZ archive) | LGPL-2.1-or-later | [zeroconf 0.152.0 source distribution](https://files.pythonhosted.org/packages/15/d2/7fa1e89251245a7135f13a653ccf0c8db46ab4ce1877007285b9da7e8865/zeroconf-0.152.0.tar.gz) |
| Seed-VC Realtime integration (Python source and its loader patch, run by an external worker) | Linux: `_internal/integrations/seed_vc/`; Windows: `_internal/voice_worker/integrations/seed_vc/` | GPL-3.0-only (license text included) | The files themselves; [seed-vc-realtime](https://github.com/jiaheguo521/seed-vc-realtime) |
| PyInstaller bootloader | `vrct-vox-sidecar` | GPL-2.0-or-later with the PyInstaller bootloader exception | [PyInstaller 6.10.0](https://pypi.org/project/pyinstaller/6.10.0/#files) |

On request through this repository's Issues, we will provide a copy of the
corresponding source code of the LGPL and GPL components above, as used in a
given release, for at least three years after that release.

PyAV is deliberately **not** included: its binary wheels bundle FFmpeg together
with the GPL-licensed x264 and x265 encoders. faster-whisper imports it only to
decode audio files, and VRCT-VOX always passes decoded audio, so builds use a
stand-in module (`packaging/pyinstaller-stubs/av`). The distribution policy
(`tools/distribution_policy.py`) rejects PyAV libraries and x264/x265 in any
build.
