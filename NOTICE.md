# NOTICE

## Optional voice integration in this fork

VRCT-VOX is an independent fork of VRCT. Original VRCT copyright and MIT
license notices are retained in `LICENSE`. The model exception below describes
the retained upstream source asset; **fork binary distributions exclude all OCR
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

## Exception: the chat-bubble detection model

| | |
|---|---|
| File (repository) | `src-python/models/ocr/onnx/chatbox_yolox_tiny.onnx` |
| File (built application) | `_internal/ocr_onnx/chatbox_yolox_tiny.onnx` |
| Copyright | Copyright (c) 2026 misyaguziya. All rights reserved. |
| License | VRCT Chat-Bubble Detection Model License Agreement — [`LICENSE.txt`](src-python/models/ocr/onnx/LICENSE.txt) (Japanese, authoritative) / [`LICENSE.en.txt`](src-python/models/ocr/onnx/LICENSE.en.txt) (English translation) |

This file is **not** covered by the MIT License in `LICENSE`. The original VRCT application code is MIT-licensed; the fork additions and
third-party components described above retain their respective notices.

### What you may and may not do

You may:

- run the model as part of VRCT on your own machine, and keep backup copies
  for that purpose;
- **run it in a fork of VRCT** while developing, fixing, testing or
  otherwise contributing to VRCT — forks do not have to strip the model out
  to be able to build and run;
- fork or mirror this repository with the model unmodified inside it,
  together with its license and copyright notice;
- redistribute an official VRCT distribution with the model unmodified
  inside it.

You may **not**:

- ship the model inside a fork's own built release (installer, executable
  distribution and the like);
- use the model in software that is not VRCT or a fork of it, or use it
  standalone;
- redistribute it separately, or sell, lend or transfer it;
- create derived models — including by further training, quantizing,
  pruning, converting or distilling it;
- use its outputs to train, evaluate or distil any machine learning model.

The agreement linked above is the authoritative statement; this section is
a summary. If you need terms beyond that, contact the copyright holder.

### Why the model is separate

The model is trained on VRChat screenshots that were collected and
annotated by hand. That dataset, and the weights produced from it, are the
part of VRCT that is not simply source code, and they are kept under the
author's own terms. The intent is narrow: keep the model from being lifted
into unrelated projects. Working on VRCT itself, in a fork, is not what
these terms are aimed at.

The base it is trained from does not constrain this. It is fine-tuned from
`yolox_tiny.pth`, the COCO-pretrained weights published by Megvii under
Apache-2.0, using YOLOX 0.3.0 (also Apache-2.0). Apache-2.0 does not claim
the trained result.

Earlier releases bundled `chatbox_yolov8n.onnx`, fine-tuned from Ultralytics
YOLOv8 weights and therefore distributed under AGPL-3.0. That model has been
replaced and is no longer shipped. Copies already obtained under AGPL-3.0
remain under AGPL-3.0; the change applies from the release that carries
`chatbox_yolox_tiny.onnx` onward. The background is in
[`docs/ocr_model_license.md`](docs/ocr_model_license.md).

### VRCT itself is unaffected

VRCT's source code stays MIT, and creating and distributing a fork is free
under the MIT License. The only consequence for a fork is that it cannot
put the model in its own released build; it can still develop and run with
it. A fork that wants to ship detection can train its own detector — the
procedure, the training configuration and the dataset preparation scripts
are all published in
[upstream VRCT](https://github.com/misyaguziya/VRCT/blob/develop/docs/ocr_yolo_training.md). VRCT also builds
and runs without the model, in which case only chat-bubble detection within
the OCR feature is unavailable.

## Third-party OCR model weights (upstream VRCT; not in VRCT-VOX builds)

Upstream VRCT bundles these weights in its own builds. VRCT-VOX builds exclude
them, as stated above; the table is kept for attribution.

| Component | Version | License |
|---|---|---|
| YOLOX `yolox_tiny.pth` (COCO-pretrained base of the model above; not shipped, used only at training time) | 0.1.1rc0 | Apache-2.0 |
| RapidOCR and the PP-OCR ONNX models it ships, fetched by `tools/fetch_ocr_models.py` | 3.9.2 | Apache-2.0 |

This table covers **model weights** only. Python package
dependencies are listed in `pyproject.toml` (resolved in `uv.lock`) and
carry their own licenses; JavaScript and Rust dependencies are listed in
`package.json` and `src-tauri/Cargo.toml`.

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
| `zeroconf` 0.39.1 (Python) | `_internal/zeroconf/` (source files, outside the PYZ archive) | LGPL-2.1-or-later | [zeroconf 0.39.1](https://pypi.org/project/zeroconf/0.39.1/#files) |
| Seed-VC Realtime integration (Python source, run by an external worker) | `_internal/integrations/seed_vc/` | GPL-3.0-only (license text included) | The files themselves; [seed-vc-realtime](https://github.com/jiaheguo521/seed-vc-realtime) |
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
