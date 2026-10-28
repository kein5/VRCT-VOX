# P4 translated microphone speech — implementation record

Status: scheduler and managed direct-branch suppression implemented; Controller/UI hookup and real-ASR/TTS acceptance still pending. This is not P4 completion.

## Scheduler (27f09d0f)

Mic translation is separately opt-in. Final mic events deduplicate by namespaced utterance; source stop invalidates pending translations and interrupts active HTTP without stopping chat. A shared worker prioritizes queued chat and bounds pending work to four. Mic startup expires five seconds after final receipt, including inference; an utterance that already began is not truncated by that startup deadline. The total request timeout remains 30 seconds. These are engineering limits, not measured latency.

Settings and scheduler tests were observed failing before implementation. Final targeted run: 80 passed. Standard suite: 1,222 passed, 6 existing skips, 46 warnings.

## Managed direct-voice branch

The fixed native `vc` selector binds the expected core cookie, node serial, name, media class and ownership marker. Existing shared-source and owned-bridge modes remain supported. One graph snapshot inspects both gates. Policy changes close the shared gate before changing the direct branch; explicit Resume is required. Branch replacement, drift and failed control revoke Resume. Unconfirmed mute remains an error, not claimed silence.

The [PipeWire core API](https://docs.pipewire.org/group__pw__core.html) describes a control/event ordering barrier. It does not provide a downstream PCM observation; this distinction is our inference about its boundary. The [loopback module](https://docs.pipewire.org/page_module_loopback.html) uses capture and playback streams, which is the basis for the existing separate branches.

Private PipeWire 1.6.10 test uses synthetic 440 Hz direct input and 880 Hz TTS input. Suppression retains only 880 Hz; explicit mix restores both. Each state is observed for two seconds. External branch drift closes the shared gate and remains muted after repair. Native tests: 25 passed, including existing helper modes. The two Resume trials reached their first qualifying private read frame in approximately 38.0 and 40.3 ms; single trials are neither a percentile nor physical/VRChat latency. Raw timestamps and observation counters are in [spoken-route-results.json](spoken-route-results.json).

Full voice regression initially exposed an existing native-test observer race: the process exited between `is_running()` and `status()`. [psutil documents `NoSuchProcess`](https://psutil.readthedocs.io/stable/index.html#psutil.NoSuchProcess) for disappearance during observation. The test now accepts that specific exit condition while preserving timeout and permission failures. Targeted native capture: 17 passed. Final voice suite: 589 passed, 13 opt-in skips, 2 warnings. Standard suite: 1,222 passed, 6 existing skips, 46 warnings. Native build, Ruff and whitespace checks passed.

## Existing multilingual model

No new model was downloaded. Existing Qwen3-TTS 0.6B CustomVoice Q8_0 matches the installed speech.cpp 0.9.0 catalog: 1,213,534,464 bytes; SHA-256 `f606ea3981aa42762b16db9a94826d2d560eb60f0b102001618f40d5a2f78cc6`. The [fixed converted card](https://huggingface.co/sakasegawa/Qwen3-TTS-12Hz-0.6B-CustomVoice-GGUF/blob/fd9df9364613a92a86b4137074bc281204823033/README.md) and [fixed upstream card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/blob/85e237c12c027371202489a0ec509ded67b5e4b5/README.md) declare Apache-2.0. The GGUF includes the decoder and tokenizer. The upstream fixed LICENSE path returned 404; the card is the available license declaration. Local inference and audible-onset measurements remain pending.

Research originals and query records: `tmp/voice-resume/research/p4-spoken-translation/` (local-only copies). Agent searches did not return results in this harness; parent performed the documented fallback research. Physical capture, VRChat, Windows native control, voice quality and GPU contention are unverified here.
