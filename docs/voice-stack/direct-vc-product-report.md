# Direct VC product integration — implementation record

The Linux direct-session owner, live external Seed adapter and Controller/browser UI hookup are implemented. One clean native product-control run has passed; intermittent-failure attribution and same-input ASR/TTS coexistence acceptance remain open. This is experimental Seed integration, not an RVC implementation or a full P2 acceptance claim.

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

Native UI acceptance, same-input ASR/TTS coexistence, sustained converted speech and input replacement acceptance remain in the plan. Physical mic, listening quality, VRChat/HMD, long mixed GPU load, Windows, RVC model/runtime selection, final artifact/license audit and release packaging are not verified by this slice.

## Controller and settings UI

The existing Start endpoint accepts explicit converted mode/options. A mode-less old payload remains passthrough. `DIRECT_VOICE_SETTINGS` stores mode/runtime/reference separately from TTS settings, and saving requires stopped input; saving invalidates earlier queued Starts. App restart restores choices but neither the selected input nor audio activity. The optional Linux backend is imported only on converted Start, keeping the regular Windows import path free of `fcntl`/Torch.

English/Japanese UI distinguishes model preparation, ready without conversion evidence, confirmed conversion, VAD silence and failure. It exposes the experimental Seed scope and local runtime/reference requirements. No automatic model acquisition or global Resume is added.

Controller RED8 → selected **70 passed** (one existing warning). Browser RED missing selector → **1 passed**, covering original-payload compatibility, saved mode/path reload, no automatic selection/start, converted state, Stop and stale snapshots. Post-hookup standard: **1,222 passed, 6 existing skips, 46 warnings** (13.99s); voice with browser/ASR opt-ins: **705 passed, 8 optional-runtime skips, 2 warnings** (71.96s). Vite/offline Tauri debug build, changed-file Ruff and whitespace checks pass. Evidence: `tmp/voice-resume/vc-controller-*.log`, `vc-ui-{red,green}.log`.

## Native product acceptance investigation (in progress)

`tests/platform/test_native_direct_vc.py` now exercises actual Tauri selection/save/start, complete synthetic speech then VAD idle, Stop during a second utterance, source removal/recreation, independent TTS-branch tone and restart with saved choices but capture off. It uses the already approved Seed runtime/reference. The TTS continuity check is an independent synthetic branch, not a real TTS model; ASR coexistence is not covered by this case.

The initial product run did **not** pass: the first full utterance worked, but the second encountered `vc_block_expired`. The stage of that original expiry was not recorded. A diagnostic retry passed the first model/Stop path but failed the second Start with `vc_capture_failed`; native stderr was not captured in that retry. Two subsequent instrumented runs passed the full product case (52.22s / 52.70s). These retries do **not** establish that the earlier failures are fixed. Forty model-free capture start/stop cycles passed on a stable private graph.

Temporary stage timestamps separated capture dequeue, transport, engine call and OS write. One retry observed a maximum successful block-end→write age of 109.50ms and engine-call durations of 38.67–97.01ms. These diagnostic observations are not percentiles, an attribution of the original fault, or measurements without instrumentation overhead. In the last successful retry, initial latency notifications changed 0→2 quanta before the first packet; deliberate source removal changed 2→0 after capture began and correctly closed it. [PipeWire documents latency propagation across links](https://docs.pipewire.org/page_latency.html). Arbitrary dynamic graphs remain an unaccepted boundary. Temporary instrumentation was removed and native helpers rebuilt before clean verification.

The existing native passthrough test separately encountered a click interception after app restart. Its saved screenshot showed the known offline notification covering the settings button. The WebDriver helper now closes that specific fixture notification through its real close control only after WebDriver reports an undelivered action. This follows the existing handling for the missing-model notice and the [WebDriver obscured-element contract](https://www.w3.org/TR/webdriver2/#element-click); no forced JavaScript click is used.

At that investigation stage, automatic approval review rejected P2 code transmission because prior permission was limited to P4. The user subsequently explicitly authorized P2; the standalone read-only review has now completed. See the review follow-up below. Do not call this plan reviewed or native acceptance complete. Raw diagnostics: `tmp/voice-resume/vc-product-{native,diagnostic,diagnostic-2,diagnostic-3}*`, `vc-stage-trace*.jsonl`, `vc-capture-restarts.json`; temporary originals are not release artifacts.

Clean verification after removing all temporary diagnostic instrumentation: native product plus legacy passthrough **2 passed** (98.49s). Legacy acceptance covers16 observations; the product case covers full synthetic speech/idle, interrupted second speech, source replacement with independent TTS-branch continuity, and restart-off. [Clean-run results](direct-vc-native-results.json). This confirms that one run passed; it does not attribute or resolve the earlier intermittent failures. The product's stop invocation→sustained private silent read was 50.58ms (one sample, 2s hold).

Further feature implementation was stopped under the user's instruction to stop when imozuru investigation has not produced a solution. The intermittent failures remain an open blocker. The newly authorized independent review resumed investigation and a bounded review-fix pass, without treating those failures as resolved. No permission was inferred from elapsed time, and no alternative model dispatch bypassed the rejection. Native ASR/VC coexistence, P5 packaging and other remaining gates were not marked complete.

Measurement limitation in the clean product run: the private observer recorded 1 read interval over100ms (maximum 110.28ms). The test passed its particular two-second settled windows, but this observer history does not establish gap-free full-stream audio. A delayed Python observer and actual audio discontinuity have not been distinguished; the result must not be used as a continuity/performance acceptance claim.

## Authorized independent review follow-up

The user explicitly authorized the P2 code/spec/diff payload. A standalone read-only Codex CLI completed successfully, with no AIT subagent dispatch; it ran48 owner/protocol/settings tests and found three issues. [Review, adjudication and fix evidence](direct-vc-review-2026-10-28.md).

The VC deadline wrapper now preserves the cancellation token's atomic nonblocking-write hook and checks block age inside that operation. Capture retains only allowlisted fixed native/adapter error codes; unknown stderr is discarded with bounded memory/work. Optional native tests defer Linux backend imports and skip on unsupported platforms. This changes neither the160ms age bound nor the fail-closed clock/latency/identity behavior. No raw-audio fallback is introduced.

Deterministic write races RED2, diagnostic failures RED9 and import failures RED2 were reproduced before correction. Selected regression78PASS; standard1,222PASS/6existingSKIP/46warnings; full voice721PASS/8optionalSKIP/2warnings (74.44s). The Windows import simulation is not Windows device acceptance. Post-fix native product+legacy verification: **2passed98.60s**. Prior intermittent faults are still unattributed.

Post-review private native run: Stop invocation→sustained silent read32.97ms (one sample,2s hold). The observer had0read gaps over100ms, max43.66ms. This does not resolve the prior110.28ms gap or establish physical/VRChat latency or long-run continuity. [Separate post-review results](direct-vc-review-native-results.json) preserve the original clean-run artifact. New feature work remains stopped under the user’s unresolved-problem rule; Task4/P2 are incomplete.
