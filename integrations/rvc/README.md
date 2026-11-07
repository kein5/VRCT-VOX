# Optional RVC worker (experimental)

The application launches this worker after an explicit converted-input Start.
Torch/RVC are not application dependencies. Models are not downloaded by this
integration. A source checkout and a separately prepared uv environment are
required. One Linux/RTX 4080 SUPER environment has passed real-model inference,
private PipeWire, 60-second continuous operation and native GUI tests using a
user-supplied model. See [validation report](../../docs/voice-stack/rvc-mia-validation-2026-10-29.md).
That private model is not included. Listening, physical mic/VRChat and
long-duration mixed-load acceptance remain open. Windows uses `venv\Scripts\python.exe`,
hash-locked `requirements-cuda-windows.lock` and `requirements-windows.lock`, and a
user-installed virtual cable; see the [Windows guide](../../docs/voice-stack/local-setup-windows.md).

Expected runtime folder:

```text
runtime/
  venv/bin/python
  engine/                 # clean Git checkout of RVC-Project/Retrieval-based-Voice-Conversion-WebUI
                          # commit 81eed5e8f68b6bed1789f682fe78cdd324495afc
  assets/hubert_base/config.json
  assets/hubert_base/preprocessor_config.json
  assets/hubert_base/pytorch_model.bin
  assets/rmvpe/rmvpe.pt
```

Choose a permitted speaker `.pth` outside or inside that folder and an optional
matching `.index`. A nonzero retrieval blend requires an index. Save only stores
intent; Start checks local files. Keep the source checkout unmodified; untracked
Python files are rejected. The source validator currently requires Git. The
runtime is trusted executable code, not an untrusted-plugin sandbox.

The qualified environment uses Python 3.12.14 and Torch/torchaudio 2.11.0+cu128 (CUDA 12.8);
until 2026-11-02 it was 2.7.1+cu118. torchaudio has no build past 2.11.0, which keeps Torch there.
`requirements-cuda.lock` and `requirements.lock` record the CUDA and inference
dependencies with hashes; `requirements.freeze.txt` records the tested environment.
The PyTorch index carries setuptools only up to 78.1.0, so the second step replaces it
with the patched version from PyPI. The 2026-11-02 refresh (Transformers 5, setuptools
84) was rechecked with the real-model tests; see the
[record](../../docs/voice-stack/vc-dependency-refresh-2026-11-02.md).
Install both into a separate uv venv, never the application venv:

```sh
uv venv --python 3.12 "$VRCT_RVC_RUNTIME/venv"
uv pip install --python "$VRCT_RVC_RUNTIME/venv/bin/python" --require-hashes \
  --index-url https://download.pytorch.org/whl/cu128 -r integrations/rvc/requirements-cuda.lock
uv pip install --python "$VRCT_RVC_RUNTIME/venv/bin/python" --require-hashes \
  -r integrations/rvc/requirements.lock
```

These commands install packages, not voice models. The engine checkout and
consented local model files remain separate prerequisites. The minimal runtime
omits upstream GUI/training packages. Its dependencies include GPLv3
`praat-parselmouth`; RVC's MIT license is not a license for every runtime component.
Final redistribution obligations for the runtime are a separate P5 gate.

The adapter calls `RVC.infer` with RMVPE, speaker 0 and formant shift 0. It accepts
v1/v2 synthesizers at 32/40/48 kHz (real-model validation so far: v2/48 kHz), with pitch -24..24 and retrieval
blend 0..1. Requested retrieval failures stop output, even if upstream catches
the exception. Missing model parameters are rejected instead of retained from
random initialization. Torch checkpoint loading is weights-only; transformers
use local files only. CUDA graphs are disabled for the first profile. The pinned
GPU eligibility function selects precision/device; CPU fallback may miss the
strict live deadline and is not claimed to be realtime.

Streaming adapts upstream's resampling and SOLA: 48 kHz input/output, 80 ms input
blocks, 40 ms overlap, 10 ms search, 2 s left history. These are **configuration
values, not a measured latency**. A fixed-size history does not itself imply a
2 s output delay. At startup the worker times a few blocks and falls back to 1 s or
0.5 s of history when 2 s does not leave room in the 80 ms block on this GPU. No VAD/denoise/RMS envelope controls are included in this first
profile. Stop/mute is the existing OS route's responsibility. Nothing falls back
to the original voice. Future measured profiles may require different settings;
the current 160 ms post-block freshness deadline has not been relaxed.

Model-free tests use fake inference with real tensor resampling/SOLA and real
worker pipes. Run them through uv with an existing optional Torch interpreter:

```sh
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --offline --no-project --with pytest==8.4.2 \
  --python tmp/voice-resume/seed-vc-poc/venv/bin/python \
  python -m pytest tests/voice/test_rvc_worker.py tests/voice/test_rvc_runtime.py -q
```

That model-free command downloads no weights and does not establish acoustic
quality or VRChat behavior. Real-model tests require explicit local paths and
opt-in flags; see `tests/platform/test_native_rvc_worker.py` and
`tests/platform/test_native_rvc_ui.py`. Record model versions/hashes, licenses
and consent before acquisition or execution. Physical mic, listening, VRChat,
controlled GPU contention and long runs remain separate gates.

Source/streaming adaptation is MIT; see `LICENSE.upstream` for RVC and the SOLA
source credited by upstream. Model rights and dependency licenses are separate.
