# Owned speech.cpp Servers Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Existing closed-loop authorization applies; no AIT subagents or external P5 review upload.

**Goal:** Start/stop bundled speech.cpp through the GUI and connect it to existing TTS/Realtime paths while preserving external endpoints.

**Architecture:** Three optional owned processes (Japanese TTS, multilingual TTS, ASR+VAD), bounded startup and native parent/thread supervision. Persist model choices and endpoint selection, never process state/ephemeral ports. Use existing HTTP adapters and cancellation generations.

**Tech Stack:** Python standard library, existing Controller and Tauri/React IPC, tiny Linux C supervisor, uv/pytest/native WebDriver.

**Spec:** [P5-B design](../specs/2026-10-29-owned-speech-servers-design.md).

## Global Constraints

- speech.cpp0.9.0 from P5-A only; no model downloads, recordings, redistribution, arbitrary commands or remote bind.
- Always127.0.0.1, port0; startup120s maximum, close3s maximum. Preserve an unclosed owner and reject restart.
- Persist no active flag, PID or port. Startup is off, external selections are defaults and existing URL settings remain.
- CPU executable SHA256 `394fd7c0636143fa96fc961af55f1bcdcf71fa557e4c210e231eb253a97353d8`; Vulkan `800e9bae0057a7ce2b63dde01a71bf83653ffbd70eb83f8bea3e8fd944f678e7`.
- Use uv and `/tmp/vrct-uv-cache`; GUI tests use display_power_guard. Approved synthetic/private graph/models only.
- Windows follows on a separate PC. AUR/package-manager discussion follows this increment; no registration/publication.

## Review Focus

- Stop racing model load/late Start must not resurrect a server or emit speech (Tasks1/2).
- Parent/creator thread/supervisor death must leave no owned server (Task1).
- A stopped bundled selection must not send audio/text to a retained external URL (Task2).
- Changing ASR endpoint selection must invalidate pending finals without stopping direct VC (Task2).
- Reopening the UI/app must show saved choices with all servers and recording off (Task3).

### Task 1: Owned runtime, strict options and native lifetime

**Files:** Create `src-python/models/speech_server/{__init__,settings,runtime}.py`, `tests/voice/test_speech_servers.py`; modify `native/vc-worker/main.c`, `tests/voice/test_vc_worker_native.py`.

**Interfaces:**
- `normalize_settings(value: dict) -> dict`: `{version:1, profiles:{japanese|multilingual|asr:{model:'',vad_model:'',voice_file:'',device:'auto'}}}`. Reject unknown keys/types/control characters; allow saved missing paths, validate files only on Start. VAD only for ASR; voice only for TTS.
- `start_options(settings: dict, profile: str) -> dict`: absolute existing regular GGUF files, primary model required, ASR VAD required, optional voice; no alias/download.
- `bundled_binary() -> Path`: fixed `build/speechcpp/speech` under application resources; validate version/variant metadata and actual pinned executable hash before execution. Missing bundle is a safe error, never PATH fallback.
- `SpeechServer(profile: str, options: dict, *, binary=None, helper=None, on_end=None)`: `start()`, immediate `stop()`, `close(timeout=3)->bool`, `health()->dict`. Single-use, states `stopped/preparing/ready/stopping/failed`, safe error code and ready base_url only. Optional injected binary/helper are dependency seams for real fake-process tests, not GUI inputs.
- `SpeechServers(*, on_end=None)`: owns3 slots; `start(profile, options, expected_generation)`, `stop(profile)`, `binding(profile)->str`, `state()->dict`, `close(timeout=3)->bool`. Generation monotonically advances on lifecycle transitions; binding refuses anything but ready.
- Native argv: `helper parent_pid creator_pidfd speech_binary speech-server model vad_or_empty voice_or_empty device` (argc9). Build only `serve MODEL [VAD] --host 127.0.0.1 --port 0 --device auto|cpu|gpu [--add-voice custom=VOICE]`. Reuse lifetime chain, keep existing VC entry points unchanged.

- [x] **Step 1: RED tests.** Use a local fake executable/HTTP server through the real native supervisor: valid argv, malformed/path/device options rejected, stop during load, wrong/missing task, no-ready timeout, stderr overflow, child exit, repeat Start busy, stale generation, bound port only after health, and all four owner death modes. Persisted defaults contain no process intent; file magic/missing-file failures spawn nothing. Add speech-server to existing supervisor lifetime matrix.
- [x] **Step 2: Verify RED.** Run `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --offline --no-project --python .venv_linux/bin/python python -m pytest tests/voice/test_speech_servers.py tests/voice/test_vc_worker_native.py -q --tb=short`. Expected missing runtime/unsupported native mode, then inspect failures.
- [x] **Step 3: Implement.** Read bounded stderr lines (64KiB maximum incomplete line), extract fixed Ready API URL, health/model metadata requests capped64KiB and0.5s socket wait; loop checks Stop every50ms. Read/discard other lines without storing raw bodies. Start deadline120s; fail-close and reap child in finally; never log model paths/transcripts. Require synthesis or recognition+detection tasks. All lifecycle callbacks run outside state locks.
- [x] **Step 4: GREEN.** Rerun Task1 command and existing seed supervisor tests; expected all PASS. Build helpers with `uv run ... python tools/build_voice_gate.py` and repeat native contracts if source changed.
- [x] **Step 5: Commit** `feat(speech): supervise bundled local inference servers`.

### Task 2: Controller settings, endpoint selection and cancellation

**Files:** Modify `src-python/config.py`, `controller.py`, `mainloop.py`, `models/tts/{settings,tts_scheduler}.py`, `models/transcription/realtime_settings.py`; create `tests/voice/test_speech_server_controls.py`; extend existing settings/scheduler/Realtime tests where appropriate.

**Interfaces:**
- Config property `SPEECH_SERVER_SETTINGS` consumes Task1 normalized settings, defaultempty paths.
- Controller `getSpeechServerSettings`, `setSpeechServerSettings`, `getSpeechServerState`, `startSpeechServer`, `stopSpeechServer`. IPC `/get/data/speech_server_settings`, `/set/data/speech_server_settings`, `/get/data/speech_server_state`, `/run/start_speech_server`, `/run/stop_speech_server`. Start payload `{profile,generation}`; Stop `{profile}`. Invalid400, busy/stale409, safe codes.
- Add Stop to the receiver's existing immediate-control lane. Test a queued Start behind a blocked ordinary command followed by Stop: Stop takes effect immediately and the old Start is rejected when drained.
- VoiceSettings adds `japanese_server`, `multilingual_server` in external|bundled. `request_for(event, *, resolve_server=None)` selects current logical role before resolving bundled URL. External-mode behavior unchanged, including multilingual server validation; bundled mode needs a resolver and never falls back.
- VoiceEventBus optional `resolve_server` callback invokes hub.binding in its existing worker, not publish/audio callbacks.
- Realtime settings add `server` external|bundled. Controller resolves selected ready URL at model listing/Start; retain configured external URL/model and tag model-list replies with server selection and URL for UI freshness.
- Controller server-end callback cancels shared TTS on an owned TTS stop/fault; for owned ASR it invalidates both Realtime sources using existing fast Stop. Direct voice stays independent. Close servers after cancelling clients at application shutdown.

- [ ] **Step 1: RED tests.** Real Controller/receiver with injectable owned-server factory: defaults/migration, valid settings roundtrip without start, stale start rejected after Stop, bundled not-ready never calls external fixture, language-specific server selection, ready server Stop cancels active/queued TTS, ASR Stop invalidates late finals and preserves direct voice, external mode requests unchanged, shutdown bounded and owns only its processes.
- [ ] **Step 2: Verify RED.** Run selected new controls tests plus existing `test_spoken_controls.py`, `test_realtime_controls.py`, `test_realtime_settings.py`, scheduler/settings tests. Expected missing endpoints/fields and behavior failures, not unrelated import failures.
- [ ] **Step 3: Implement minimal hooks.** Preserve existing locks/generations and avoid callbacks under hub locks. Endpoint selection change counts as a shared ASR setting change. Saved changes do not load models. A failing optional server cannot break legacy chat/OSC delivery.
- [ ] **Step 4: GREEN and voice regression.** Run the selected tests then `uv run ... python -m pytest tests/voice -q`. Expected only documented opt-in skips; identify any unexpected failures.
- [ ] **Step 5: Commit** `feat(speech): bind managed servers to TTS and realtime ASR`.

### Task 3: GUI controls and actual bundled model acceptance

**Files:** Create `src-ui/logics/voice/useSpeechServers.js`, `advanced_settings/SpeechServers.jsx` beside VoiceSettings; modify `src-ui/logics/useReceiveRoutes.js`, `VoiceSettings.jsx`, `transcription/RealtimeASRSettings.jsx`, `locales/{en,ja,ko,zh-Hans,zh-Hant}.yml`; create `tests/platform/test_native_speech_servers.py` and `docs/voice-stack/owned-speech-servers-report.md`.

**Interfaces:** Hook routes the five Task2 endpoints; status per profile has generation so old polls cannot undo Stop. UI emits Start with current generation, saves only normalized profile fields. Endpoint selection dropdowns preserve hidden external URLs. ASR model-list freshness includes server selection to avoid accepting external list after switching to bundled.

- [ ] **Step 1: RED browser tests.** Exercise real form/save/start/stop/state handling via existing component test harness; defaults, incomplete choices, busy/stale state, errors/retry, language switching and retained external URLs. No synthetic test-only product controls.
- [ ] **Step 2: Verify RED, implement UI and translations, then GREEN.** Run affected browser tests and `npm run build`; preserve native navigation conventions from existing tests.
- [ ] **Step 3: Real native acceptance.** Stage verified bundle at dev resource path, use display guard and private network/PipeWire. Through UI select approved Qwen and ASR/VAD GGUFs, Start, obtain synthesis and captions from synthetic input, Stop during activity, close/restart with saved choices and all servers/input off. Keep an external fixture server alive to prove ownership scope. No new model/voice acquisition. Record failure/Stop results and real source/version.
- [ ] **Step 4: Review and regression.** Run standard Python suite, affected voice/native/UI checks; local review because P5 external-review transmission has not been authorized. Fix reproduced issues under RED→GREEN. Record actual commands/results and unverified physical/Windows/license/quality boundaries.
- [ ] **Step 5: Commit** GUI integration and report; update completion ledger. Continue with Linux packaging/AUR design discussion under the user's latest steering, and retain the final Trail of Bits security gate before publication.
