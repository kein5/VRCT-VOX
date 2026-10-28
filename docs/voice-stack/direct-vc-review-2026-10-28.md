# P2 independent review and correction record

The user explicitly authorized sending P2 code/spec/diffs to OpenAI Codex. The
standalone read-only CLI completed with exit0; no AIT subagent was dispatched.
The input excluded audio, weights, credentials and unrelated diagnostics. The
reviewer ran48 owner/protocol/settings tests, all passing, and did not claim to
run native acceptance. This is the plan's one independent review; corrections
use regression tests rather than another review cycle.

## Findings and adjudication

| Finding | Reviewer | Adjudication and correction |
|---|---|---|
| Stop could finish between the last output check and an unprotected OS write | High | Important. `_Deadline` now exposes `commit_audio_write`, delegates to the cancellation lock and checks freshness inside the protected nonblocking write. |
| Native capture errors were discarded, then every callback became `vc_capture_failed` | Medium | Important: this prevents diagnosing an acceptance blocker. Preserve allowlisted fixed codes through startup exceptions and callbacks; drain stderr without retaining unknown messages. |
| Optional native VC tests imported Unix `fcntl` before skip evaluation | Low | Important for compatibility: collection fails even without opt-in. Defer backend/fixture imports and guard Linux-only tests. |

The diagnostic reader keeps at most96 incomplete-line bytes and drains at most
64KiB per capture iteration. An oversized line is discarded through its newline,
so a valid-looking suffix cannot be mistaken for a diagnostic. Neither model
output nor arbitrary driver text is exposed in health. Helper exit without a
recognized code remains `asr_capture_helper_closed`; startup timeout remains
distinct. Cleanup and no-reconnect behavior are preserved.

The Stop correction serializes cancellation with an actual nonblocking write;
it does not retract audio previously accepted by the OS. That downstream tail
still needs private-source observation. Block age remains160ms beyond input
block end, and the existing clock/latency-change guards remain intact.

## Reproduction and verification

- Actual kernel pipe, no audio device: inject cancellation or expiry after the
  last readiness check. Both cases failed before the fix (RED2), then passed
  with zero pipe bytes; combined output/adapter regression37PASS.
- Actual child pipes, no model/device: noisy oversized and fragmented stderr,
  native latency/clock errors, silent helper exit, startup timeout, callback and
  raised-error propagation, unknown-text exclusion. RED9 failures with3 existing
  passes; corrected capture/adapter regression31PASS.
- Two optional native modules with `fcntl` unavailable: RED2 collection errors,
  then both import successfully. This simulates the dependency boundary, not a
  Windows runtime/device test.
- Combined selected78PASS (2.25s); standard1,222PASS/6existingSKIP/46warnings
  (14.50s); full voice721PASS/8optionalSKIP/2warnings (74.44s). Changed-file Ruff
  and whitespace checks passed. No renderer or native-helper source changed.

Raw local records: `tmp/voice-resume/vc-review-{write,diagnostics,collection}-red.log`,
`vc-review-selected-green.log`, `vc-review-standard.log`, `vc-review-voice.log`.
The original review and execution ledger remain in the plan's ignored workspace
because Task4 is incomplete.

## Intermittent failure remains open

The reviewer could not attribute the earlier `vc_block_expired` or failed second
Start. A successful retry cannot establish a fix. The deadline code also covers
future timestamps, so its name alone does not prove inference overload. Existing
successful-stage timings do not identify the uninstrumented failing stage.

The documented2→0 latency change occurred on deliberate source removal; it is
not evidence of the earlier startup failure. Next failure evidence must retain
the terminal capture code, timing phase, block sequence/age, queue occupancy and
graph-check duration without PCM. Same-source native ASR/VC and actual TTS-model
coexistence, listening quality, physical/VRChat/HMD, sustained load, Windows and
distribution/license acceptance remain open.

## Original-source trace

The imozuru trace follows the local VC wrapper to `PipeWireOutput.write`, then
to the existing cancellation-token commit operation. Mutual exclusion is checked
against [Python3.11 lock semantics](https://docs.python.org/3.11/library/threading.html#lock-objects),
and partial writes/EAGAIN against [Linux write(2)](https://man7.org/linux/man-pages/man2/write.2.html).
Original pages and pre-fix source snapshots are saved under
`tmp/voice-resume/research/p2-direct-vc-design/sources/`; map/log record the trace.
The existing [PipeWire latency specification](https://docs.pipewire.org/page_latency.html)
remains the basis for treating graph latency changes separately from model timing.

## Post-fix native verification and stop decision

Actual Tauri converted controls plus legacy passthrough: **2PASS98.60s** under
the display-power guard, private network and private PipeWire. Product Stop to
sustained silent read32.97ms (one sample,2s hold); observer0gaps over100ms, maximum
43.66ms. [Sanitized results](direct-vc-review-native-results.json) are separate
from the earlier artifact. The earlier110.28ms observer gap and intermittent
faults are not retroactively resolved.

The review’s three reproducible issues are corrected. No additional feature
implementation proceeds because imozuru and the review still cannot attribute
the earlier native failures, matching the user’s explicit stop condition. P2
Task4 remains incomplete. No upstream contact, PR, push or release occurred.
