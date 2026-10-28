# Direct VC product integration — implementation record

The Linux direct-session owner and live external Seed adapter are implemented as components. Controller/UI hookup is still pending. This is experimental Seed integration, not an RVC implementation or a full P2 acceptance claim.

The owner makes passthrough and conversion mutually exclusive, requires Stop and completed cleanup before changing producers, and does not fall back to original audio. The app sends timestamped 48kHz mono S16 blocks to a separate optional GPL worker. Only the worker imports Seed/Torch. It uses the already approved local runtime, pinned model assets and permitted reference; no download or physical recording was performed.

The protocol authenticates the session/sequence/format and rejects malformed, late, replayed and bypass results. `vad_silence` must be all zero; a nonzero exact copy of the input is rejected. These checks prove execution state and basic integrity, not perceptual conversion quality. 80ms blocks, one queued complete block, 160ms maximum age beyond block end, 60s startup and 1s response limits are engineering bounds, not measured E2E performance. Startup warms the model and resampler before capture. Output targets the bound sink serial, forbids fallback/reconnection, and supervises source/sink identities.

A small native supervisor follows the existing source-bridge creator-thread pidfd/PDEATHSIG pattern. It starts only the fixed worker module, passes binary pipes through, and kills the worker if its parent, creating thread or supervisor exits. Four model-free lifetime tests pass. Stop invalidates delivery without waiting on inference; cleanup occurs on the owned background thread. Incomplete cleanup cannot authorize a replacement producer.

## Verification

Protocol/owner/adapter/output and existing Seed model-free regression: **105 passed, 6 optional-runtime skips** (1.88s). Worker resampling/integrity tests: **7 passed** (0.19s) using the existing isolated Seed interpreter with cached pytest via uv. The app interpreter deliberately does not acquire SciPy/Torch; that optional test module skips there. Standard regression: **1,222 passed, 6 existing skips, 46 warnings** (14.56s). Full voice regression with browser/ASR opt-ins: **689 passed, 8 optional-runtime skips, 2 warnings** (75.03s). All modified native helpers build; changed-file Ruff and whitespace checks pass.

The private native test uses the existing consented synthetic Japanese input and reference with actual Seed inference. Both explicit Stop and supervisor SIGKILL passed (**2 tests, 32.25s**): a real converted block reached the private source, then output stayed silent for two seconds; replaying input after termination remained silent. The managed endpoint survived. Model-ready was not counted as conversion.

| Trial | Blocks written (includes VAD silence) | Capture block end bound → successful OS write (min–max ms) | Stop/fault invocation → first sustained silent private read (ms) |
|---|---:|---:|---:|
| Explicit Stop | 37 | 53.36–59.17 | 80.85 |
| Worker supervisor death | 36 | 50.72–58.18 | 80.89 |

Each trial stopped early during the utterance after two confirmed converted blocks. The remaining blocks are VAD silence. These ranges are **not model-only processing time**, capture-to-audible latency, p50/p95, physical microphone or VRChat measurements. Native capture reports a timestamp bound; the write boundary includes capture delivery, aggregation, transport, inference and local output readiness. The minimum/maximum do not establish steady-state quality or long-run throughput. [Detailed measurements](direct-vc-live-results.json).

Raw evidence: `tmp/voice-resume/vc-{live,worker,adapter}*.log`, `tmp/voice-resume/vc-live-native/`. The existing file-input PoC remains unchanged. The app remains MIT and the optional integration files retain GPL-3.0-only notices; process separation alone does not establish distribution compliance.

## Remaining gates

Controller/native UI connection, same-input ASR/TTS coexistence, sustained converted speech and input replacement acceptance remain in the plan. Physical mic, listening quality, VRChat/HMD, long mixed GPU load, Windows, RVC model/runtime selection, final artifact/license audit and release packaging are not verified by this slice.
