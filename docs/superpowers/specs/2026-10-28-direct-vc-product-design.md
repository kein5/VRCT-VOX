# Direct VC product integration — Linux slice

Implements the user-approved external-inference/OS-route direction and the
[source investigation](../../voice-stack/direct-vc-integration-research-2026-10-28.md).
The user authorized continuous implementation and independent selectable paths;
routine implementation choices below are the implementer's decisions.

## Behavior

Direct microphone output has an explicit choice: original passthrough or
experimental Seed-VC conversion. Stop means off. Only one direct producer may
exist at a time. A change requires Stop and completed cleanup before Start.
Initial application startup never captures, converts, or restores direct output.
Global mute/Resume and managed translated-TTS suppression/mix remain separate.
Stopping or failing direct VC does not stop ASR, chat, translation or TTS. Failed
conversion never switches to original audio. The shared virtual microphone
survives producer shutdown.

Use the existing approved Seed runtime, assets and permitted local reference
WAV. No new models, downloads, recording or RVC model acquisition. This is an
experimental engine hookup, not final VC selection or a quality/performance pass.
RVC uses a later engine-specific adapter after model/license/runtime validation.
Windows implementation and device tests remain assigned to the later Windows PC.

## Minimal components

- A direct-session owner chooses the existing SourceBridge or a Seed process
  adapter. It owns request generations, prevents overlapping producers and
  invalidates delayed starts. No general plugin framework.
- The application adapter uses the existing identity-bound PipeWireCapture:
  48kHz mono S16, timestamped 20ms frames. ASR may independently capture the same
  original source. Native capture excludes managed output/feedback nodes.
- A fixed external `integrations.seed_vc.live_worker` runs in the isolated uv
  environment. Only this optional GPL-3.0 component imports Torch/Seed. The normal
  application never imports the GPL worker, Torch or the model loader.
- A bounded binary stdin/stdout protocol carries audio and session/sequence/time
  metadata between adapter and worker. PCM never enters UI JSON/stdio IPC.
  The existing file-input PoC protocol remains unchanged.
- Verified fresh converted/VAD-silence packets feed the managed direct sink;
  existing global/source identity gates remain authoritative. No additional
  persistent virtual microphone or user-facing graph abstraction.

## Lifecycle and bounds

1. Validate explicit endpoint identity, runtime paths and reference. Launch the
   fixed module without a shell. Validate local artifacts before model load.
2. Warm the model before opening capture. Distinguish preparing, ready/idle,
   converting and failed. Model-ready alone is not conversion success.
3. Use the tested `low` profile: 80ms input blocks, 20ms right context, 10 steps,
   2.5s CE history, 0.5s DiT history and 3s prompt. Settings are fixed initially.
   Parent aggregates four 20ms input frames. At most one unsent complete block
   is buffered; input callback never waits for inference/pipe writes.
4. Each stream has a random session ID and monotonically increasing sequence.
   Worker output must match its outstanding input, exact PCM shape and accepted
   state. `vad_silence` must contain zero PCM. Nonfinite tensors, bypass, missing
   model, EOF, malformed/late/replayed output and queue overflow fail closed.
5. Start timeout is 60s; running packet timeout is 1s. Completed block age is
   bounded to two block durations beyond the input block's end timestamp,
   including OS writes. These are engineering limits, not measured E2E latency.
6. Stop invalidates generation and capture delivery immediately, cancels writes,
   closes/reaps the worker and waits for cleanup on a non-receiver path. No new
   start until old cleanup completes. Explicit new Start is required after error.
7. Store only paths/settings and aggregate diagnostic codes, never captured PCM,
   reference contents or recognized text in default logs. Native synthetic
   acceptance may record its own generated fixtures for verification.

## Controls and compatibility

Keep existing direct-input selection, refresh, Start and Stop endpoints. Missing
`mode` in an old start payload means passthrough. Add mode and optional Seed
runtime/reference fields; never turn an invalid mode into passthrough. Retain
source identity strings to avoid JS rounding of 64-bit serials. Settings changes
do not start capture. UI explains experimental Seed scope and exposes preparing,
idle/converted/failure truthfully; endpoint connectivity is not conversion proof.

## Acceptance and remaining gates

Model-free tests cover exclusive ownership, generation races, stop while
starting, failed worker, no raw fallback, packet validation, overflow, stalled
inference and shutdown. Private PipeWire tests use synthetic input and mock
workers; opt-in real Seed tests use only existing permitted assets. Native UI
tests cover explicit selection/start/stop/restart-off and coexistence with TTS
and original ASR. Preserve existing SourceBridge and P1/P3/P4 regressions.

Report model processing and capture-to-private-source separately. Physical mic,
VRChat/HMD, subjective voice quality, 30-minute mixed GPU load, p50/p95 targets,
Windows and distribution/license review remain independent gates. Optional GPL
components and dependency/model notices must remain explicit; process isolation
does not itself establish distribution compliance.
