# Seed-VC offline PoC

This optional external experiment is GPL-3.0-only (see [LICENSE](LICENSE)),
separate from the application runtime. It is not a bundled production engine.
Code/model/dependency distribution obligations still require release review;
using another process does not remove them. No weights or private audio belong
in Git. See the [consented artifact proposal](../../docs/voice-stack/vc-engine-poc-proposal.md).

The upstream source is
`jiaheguo521/seed-vc-realtime@58d0ca372cc76f60a798d9f84611f053f9029f3a`.
`loader.py` adapts its model construction. Apply `offline-loader.patch` to that
checkout: it supplies local model loading, defers PortAudio imports, and allows
explicit channels during block preparation. It does not change the inference
algorithm. Keep the original upstream copyright/license notices.

Use an isolated **Linux x86-64 Python 3.11** environment with uv. The lock is
platform-specific; it pins the three CUDA wheels by official URL/hash and the
remaining dependencies by version/hash. Do not subsequently install upstream's
original requirements, which request torch 2.4 while naming the CUDA 12.8 index.

```bash
uv venv --python 3.11 tmp/seed-runtime
uv pip sync --python tmp/seed-runtime/bin/python --require-hashes integrations/seed_vc/requirements.lock
git -C "$SEED_ENGINE" apply "$PWD/integrations/seed_vc/offline-loader.patch"
uv run --no-project --python tmp/seed-runtime/bin/python python -m integrations.seed_vc.smoke \
  --engine "$SEED_ENGINE" --assets "$SEED_ASSETS" --reference "$PERMITTED_REFERENCE" \
  --report tmp/seed-load.json
```

Asset layout is produced by `tools/seedvc_artifacts.py`, after user consent for
the exact manifest. The reference must be a permitted local WAV of 1–30 seconds.
Only metadata/hash appears in the report. The smoke test opens no audio device
and reports `converted: false` even when all five models load.

Every manifest file is rehashed before heavy imports. All required model state
keys and shapes are checked before strict loading. Two deterministic Seed
buffers have an explicit old-schema migration, backed by upstream commits
[`1a639856`](https://github.com/Plachtaa/seed-vc/commit/1a639856acc60545d777c8680a3612c07cf64b6a)
and [`c32991ca`](https://github.com/Plachtaa/seed-vc/commit/c32991ca4ae283b4730a4a5afca7fe39f545d820):
missing timestep frequencies are regenerated in float32; the old int64 position
buffer must equal `arange(8192)` before expanding to `arange(16384)`.
CAMPPlus's official old-key rename is applied before checking completeness.
Unused checkpoint tensors are counted separately, not represented as loaded.

The approved HF FSMN-VAD is built directly from its local config and CMVN;
it is not asserted identical to the upstream ModelScope `v2.0.4` alias.
`model_conf` avoids hub resolution. The wrapper loads its state strictly instead
of using FunASR's partial initialization helper. Restricted `weights_only=True`
loading remains enabled throughout. Torch 2.10 addresses the two advisories
reviewed for this experiment; this is not a full dependency security audit.

For observed offline verification, run in a network namespace and trace network
syscalls. HF offline flags alone are not a network sandbox. The reported
load/VAD timings include initialization and may include tracing overhead;
they are not conversion or microphone-to-VRChat latency.

The optional real-runtime tests use `VRCT_SEED_POC` pointing to a private root
containing `venv`, patched `engine`, `assets`, and `private-inputs/reference.wav`.
Ordinary tests need no models or CUDA. Never set the optional variable on a
machine lacking the prior model and audio permissions.
