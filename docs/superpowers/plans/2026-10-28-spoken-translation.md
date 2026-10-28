# Spoken Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Realtime mic final translations speak once through the selected TTS server and virtual microphone, with source cancellation and direct-voice exclusion.

**Architecture:** Extend the existing single VoiceEventBus and VoiceRoute. Preserve the real message pipeline and external inference boundaries; no second audio worker or new framework.

**Tech Stack:** Python 3.11/uv/pytest, existing HTTP PCM and PipeWire native helper, React/Tauri.

**Spec:** ../specs/2026-10-28-spoken-translation-design.md

## Global Constraints

- New mic speech OFF; no automatic ASR start, recording or model download.
- Queue total 4; mic first playback deadline final receipt + 5s; request deadline 30s.
- No speaker/partial/failed-translation speech. No fallback to original.
- Existing P1 payload and chat semantics retained. No new runtime dependency/license.
- User authorized inline continuous work. No push, publication, upstream communication or PR.

## Review Focus

- Settings/target changes during translation must not select a different result or resurrect cancelled work (Task 3).
- A delayed old ASR cleanup must not cancel a replacement owner; source-only stop leaves chat intact (Tasks 1/3).
- Gate acknowledgment or same-name replacement must not be mistaken for verified silent direct audio (Task 2).
- Expiring before first audio must interrupt stalled HTTP but never expire a valid already-started utterance merely due to queue age (Task 1).
- Optional speech errors must not break existing caption/OSC/WebSocket delivery or disclose content (Tasks 3/4).

### Task 1: Source-aware TTS scheduling and settings

**Files:** src-python/models/tts/{settings,tts_scheduler,speechcpp_tts,message_hook}.py, src-python/models/audio_routing/audio_router.py; tests/voice/test_spoken_scheduler.py plus existing TTS/scheduler tests.
**Interfaces:** VoiceSettings adds mic_mode/direct_policy strings. Bus adds source_generation(source)->int and cancel_source(source)->None; publish accepts expected_source_generation. CancelToken adds start deadline/atomic playback-start signaling; existing constructor/methods remain compatible. AudioRouter marks first non-silent PCM start before write. SpeechMessageEvent remains source-tagged immutable payload.

- [x] Write/observe RED for enabled final mic translation, missing/failed selection, source stop and late generation, bounded priority/overflow, aged queued work and slow first PCM, no expiry after start. Existing chat and remote exclusions remain.
- [x] Implement minimal settings validation, source generation, queue priority and bounded start cancellation; no Controller or native changes yet.
- [x] Run `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python python -m pytest -q tests/voice/test_spoken_scheduler.py tests/voice/test_scheduler.py tests/voice/test_tts.py tests/voice/test_audio_router.py` → PASS. Commit independently testable scheduler.

### Task 2: Managed direct-voice suppression

**Files:** native/voice-gate/main.c; src-python/models/audio_routing/{pipewire_gate,managed_route}.py; tests/voice/{test_pipewire_gate,test_managed_route,test_spoken_route_native}.py; tools acceptance harness if needed.
**Interfaces:** PipeWireGate.inspect_pair()->{source:{identity,muted},direct:{identity,muted}}; set_direct_muted(value,identity)->state. VoiceRoute.configure(managed, timeout=3, *, suppress_direct=False); status adds requested/observed direct suppression. Existing source set_muted and owned bridge helper arguments unchanged.

- [ ] Write/observe RED for isolated direct branch identity/mute, fixed native selector, policy switch latch, failed/drifting/recreated branch and no implicit Resume.
- [ ] Confirm PipeWire original-source contract; add fixed `vc` helper selector and route policy with main-gate-first transitions.
- [ ] Build native helpers with `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python python tools/build_voice_gate.py` → PASS; run unit route regressions → PASS.
- [ ] Run private PipeWire synthetic tone test → direct suppressed/TTS audible, mix/restoration, fail/recreation honest status. Commit route slice and measurements with boundaries.

### Task 3: Controller and UI connection

**Files:** src-python/controller.py; src-python/models/tts/message_hook.py; src-ui VoiceSettings/useVoice and en/ja locale files; tests/voice/test_spoken_controls.py and browser acceptance.
**Interfaces:** Trusted TranscriptUpdate passed only from realtime mic process callback; pipeline snapshots voice generations/settings/target mappings before translation, supplies real success flags to the mic event builder. Invalidate/terminal callbacks cancel mic by owner generation. UI existing settings IPC carries added string fields; global Resume remains explicit.

- [ ] Write/observe RED for successful selected mic final once; off/partial/speaker/OCR/failed-translation never speak; stop while translation blocks; target/config change; old owner cleanup; mic stop while chat queued/active.
- [ ] Connect pipeline and cancellation; preserve legacy payloads and optional-error isolation. Expose mic mode/direct policy and truthful managed scope in UI with English/Japanese strings.
- [ ] Verify real Controller + local HTTP PCM, existing pipeline suite, UI persistence/restart/no-auto-capture and error transitions → PASS; Vite build → PASS. Commit connected feature.

### Task 4: Native acceptance, report and review

**Files:** tests/platform/test_native_spoken_translation.py or an extension of the existing native realtime acceptance; docs/voice-stack spoken report/results, completion ledger.

- [ ] Exercise real Tauri/Controller/ASR/VAD/TTS through private PipeWire using approved synthetic input. Fixed local translation fixture remains labeled as such. Multilingual inference is opt-in after fixed-model consent.
- [ ] Measure final receipt→first PCM write and private virtual-source onset separately; do not infer physical/VRChat latency. Verify one utterance, source stop silence and TTS/direct exclusion.
- [ ] Run default pytest plus voice regression with appropriate approved-model opt-ins and browser tests; Ruff/diff/build checks → PASS. Record all remaining gates rather than declaring all P4/P5 accepted.
- [ ] One fresh final review across this plan, one RED→GREEN important-finding fix pass, no re-review. Commit reports. Preserve worktree/ledger for continued full-feature work.
