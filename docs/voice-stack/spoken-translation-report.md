# P4 translated microphone speech — implementation record

Status: scheduler, managed direct-branch suppression, Controller/UI hookup and Linux private-graph native ASR/VAD/TTS acceptance implemented and tested. Independent read-only Codex review completed; all three findings were reproduced and fixed. Final native verification is recorded below. This is not full P4 acceptance.

## Scheduler (27f09d0f)

Mic translation is separately opt-in. Final mic events deduplicate by namespaced utterance; source stop invalidates pending translations and interrupts active HTTP without stopping chat. A shared worker prioritizes queued chat and bounds pending work to four. Mic startup expires five seconds after final receipt, including inference; an utterance that already began is not truncated by that startup deadline. The total request timeout remains 30 seconds. These are engineering limits, not measured latency.

Settings and scheduler tests were observed failing before implementation. Final targeted run: 80 passed. Standard suite: 1,222 passed, 6 existing skips, 46 warnings.

## Managed direct-voice branch

The fixed native `vc` selector binds the expected core cookie, node serial, name, media class and ownership marker. Existing shared-source and owned-bridge modes remain supported. One graph snapshot inspects both gates. Policy changes close the shared gate before changing the direct branch; explicit Resume is required. Branch replacement, drift and failed control revoke Resume. Unconfirmed mute remains an error, not claimed silence.

The [PipeWire core API](https://docs.pipewire.org/group__pw__core.html) describes a control/event ordering barrier. It does not provide a downstream PCM observation; this distinction is our inference about its boundary. The [loopback module](https://docs.pipewire.org/page_module_loopback.html) uses capture and playback streams, which is the basis for the existing separate branches.

Private PipeWire 1.6.10 test uses synthetic 440 Hz direct input and 880 Hz TTS input. Suppression retains only 880 Hz; explicit mix restores both. Each state is observed for two seconds. External branch drift closes the shared gate and remains muted after repair. Native tests: 25 passed, including existing helper modes. The two Resume trials reached their first qualifying private read frame in approximately 38.0 and 40.3 ms; single trials are neither a percentile nor physical/VRChat latency. Raw timestamps and observation counters are in [spoken-route-results.json](spoken-route-results.json).

Full voice regression initially exposed an existing native-test observer race: the process exited between `is_running()` and `status()`. [psutil documents `NoSuchProcess`](https://psutil.readthedocs.io/stable/index.html#psutil.NoSuchProcess) for disappearance during observation. The test now accepts that specific exit condition while preserving timeout and permission failures. Targeted native capture: 17 passed. Final voice suite: 589 passed, 13 opt-in skips, 2 warnings. Standard suite: 1,222 passed, 6 existing skips, 46 warnings. Native build, Ruff and whitespace checks passed.

## Existing multilingual model

No new model was downloaded. Existing Qwen3-TTS 0.6B CustomVoice Q8_0 matches the installed speech.cpp 0.9.0 catalog: 1,213,534,464 bytes; SHA-256 `f606ea3981aa42762b16db9a94826d2d560eb60f0b102001618f40d5a2f78cc6`. The [fixed converted card](https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-0.6B-CustomVoice-GGUF/blob/fd9df9364613a92a86b4137074bc281204823033/README.md) and [fixed upstream card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/blob/85e237c12c027371202489a0ec509ded67b5e4b5/README.md) declare Apache-2.0. The GGUF includes the decoder and tokenizer. The upstream fixed LICENSE path returned 404; the card is the available license declaration. Local warmed inference and private virtual-source onset measurements are recorded below. Physical/VRChat onset remains unmeasured.

Research originals and query records: `tmp/voice-resume/research/p4-spoken-translation/` (local-only copies). Agent searches did not return results in this harness; parent performed the documented fallback research. Physical capture, VRChat, Windows native control, voice quality and GPU contention are unverified here.

## Controller and UI

Only the Realtime microphone callback supplies the trusted final transcript. The pipeline snapshots settings/generations and enabled target order before translation. A selected successful translation publishes once; failed translations cannot fall back to speaking the original. Source stop, session failure and translation settings changes cancel microphone speech. Late cleanup from an old ASR session cannot cancel a newer owner. Optional enqueue failure leaves captions, OSC and history intact.

English/Japanese controls persist mic mode and direct policy through existing settings IPC. Browser save/reload does not start capture or forwarding. Existing chat label and payload remain compatible. Controller-specific tests: 19 passed; browser integration: 1 passed; standard suite: 1,222 passed/6 existing skips/46 warnings; voice including both browser integrations: 610 passed/11 opt-in skips/2 warnings. Vite and offline Tauri debug build pass.

The voice run exposed one intermittent preexisting native capture failure (`asr_capture_latency_changed`). A temporary instrumented helper observed initial propagation from zero to two quanta for mic, one for speaker; the original failing transition itself was not recorded. The fixed-topology test now requires an observed synthetic tone before opening the measured capture, instead of assuming producer process creation means negotiation is complete. Targeted tests and full rerun passed. Runtime termination on latency changes remains intact; arbitrary dynamic graphs may still require explicit restart. [PipeWire latency propagation](https://docs.pipewire.org/page_latency.html) is the original API basis for this distinction.

## Native translated speech and combined paths

`tests/platform/test_native_spoken_translation.py` drives the real Tauri UI, Controller, speech.cpp ReazonSpeech/Silero VAD and Qwen3 TTS. A deterministic HTTP fixture uses the production LMStudio translation adapter; this does not measure a real translation model. Existing, consented synthetic input supplies microphone capture, and a separate continuous 440 Hz producer represents direct audio. Shared physical-mic capture/fan-out is not verified by this fixture.

Two settings were accepted: `suppress` closes the managed direct branch while translated mic mode is enabled; explicit `mix` retains that branch alongside TTS. Each of two spoken translations occurs exactly once by recorded PCM envelope comparison. Each final sends one `/chatbox/input` datagram containing both original and translated text. In mix, the direct tone was detected in all measured frames during both TTS utterances. Dynamic TTS-only ducking is not implemented by this mode.

Opening configuration pauses the existing translation feature. The first corrected native test therefore exposed missing source-specific Stop access on Main. A compact main-view control now stops microphone or game-audio captions through the existing endpoint. Native RED had a missing/non-interactable Stop; GREEN verifies both buttons and actual capture termination. The WebDriver helper selects the visible matching label while retaining native hit testing. Screenshot inspection confirmed controls and original/translated rows render without overlap.

Suppression acceptance stops during an active long TTS utterance, observes cancellation and sustained silence, then replays input and confirms no new translation/TTS. Mix acceptance stops capture after its two utterances, confirms direct tone continues, and rejects new translation/TTS from replay. It does not claim active-TTS interruption was acoustically measured during mixed tone. App close/restart remains globally muted and starts no capture.

| Boundary | Observed values (ms) |
|---|---:|
| Final receipt → first PCM write, suppress | 148.30 / 40.97 |
| Final receipt → first nonzero private-source read, suppress | 648.94 / 508.46 |
| Final receipt → first PCM write, mix | 133.61 / 40.34 |
| Stop button invocation → first sustained silent private-source read, suppress | 84.50 |

These are warm individual samples, not p50/p95, physical microphone latency, VRChat latency, or author model benchmarks. Receipt begins before the fixture translation. Read onset and first write include different buffering boundaries; their difference has not been attributed to a single component. Nonzero read cannot identify TTS onset during the continuous mixed tone, so that metric is intentionally absent for mix. Each stable route is observed for two seconds. [Machine-readable summary](spoken-native-results.json).

Pre-review verification: native combined-path plus mic/speaker caption acceptance **3 passed** (114.98s); standard **1,222 passed, 6 existing skips, 46 warnings** (14.22s); voice with browser/model opt-ins **614 passed, 7 consented-runtime opt-in skips, 2 warnings** (73.71s). Ruff and whitespace checks pass. Vite and offline Tauri debug build pass (existing Vite chunk-size advisory). The initial sandboxed standard run failed four tests: two directly denied local UDP sockets, and two telemetry assertions. The unchanged suite passed in a network namespace with loopback enabled and external networking absent; the telemetry subcause was not separately established.

Raw local evidence: `tmp/voice-resume/spoken-native-final/`, `spoken-native-final.log`, `spoken-standard-isolated-final.log`, `spoken-voice-final.log`. GPU contention, physical microphone/VRChat, HMD, Windows, translation quality, perceptual VC quality and long-run mixed workloads remain unverified.


## Independent review and fixes

The explicitly authorized read-only Codex CLI review completed without AIT child-agent messaging. It reported one Important finding and two Minor findings; both Minors were treated as Important because they could preserve or start stale speech. No Critical findings were reported. One fix pass was performed; no second review is claimed.

- Resume now binds the shared source and direct branch identity/policy in the native helper, checks the branch before/after the source mutation, and confirms both in one graph snapshot before opening software playback. Drift/replacement during Resume retains the mute latch. Control ordering is not atomic multi-node mutation or downstream PCM silence; later external changes remain subject to monitoring.
- Accepting a replacement microphone session cancels its predecessor's speech before advancing ownership. Late predecessor cleanup still cannot cancel the new session.
- Startup expiry remains active while output readiness waits. Linux commits the transition under the cancellation lock at the first successful nonzero nonblocking OS write. Failed writes and silent partial writes retain expiry. Windows hardware write behavior remains unverified.

Regression reproduction: four original failing cases plus six native/first-write-boundary failures. During the fix pass, three native regressions exposed a params-only notification being mistaken for identity loss. A temporary private-graph probe observed change masks 31 then 16, with empty properties in the latter. The [PipeWire node information contract](https://docs.pipewire.org/structpw__node__info.html) and [linked header](https://docs.pipewire.org/src_2pipewire_2node_8h_source.html) define a mask for changed fields; both listeners now validate properties only when that bit is set. Changed-null properties still invalidate the binding. The corrected selected suite passed **110 tests** (one existing warning).

Post-fix standard suite: **1,222 passed, 6 existing skips, 46 warnings** (13.96s). Voice suite including browser/model opt-ins and current P2 component tests: **665 passed, 7 optional Seed runtime skips, 2 warnings** (70.19s). Native helper build, Vite, offline Tauri debug build, changed-file Ruff and whitespace checks passed. Raw evidence: `tmp/voice-resume/p4-review-*.log`; local original-source trace: `tmp/voice-resume/research/p4-spoken-translation/`.

Post-fix native combined-path/caption acceptance: **3 passed** (106.79s), DPMS guard active. The table and JSON above use this post-fix run. Raw native evidence: `tmp/voice-resume/p4-review-native/` and `p4-review-native.log`. Physical/VRChat, real MT quality/latency, HMD, Windows, perceptual VC quality and long-run contention remain open.
