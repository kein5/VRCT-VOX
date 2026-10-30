# Direct VC Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explicit Linux microphone original/Seed-VC output selection with fail-closed conversion and independent ASR/TTS paths.

**Architecture:** A small exclusive direct-session owner wraps the existing SourceBridge and an external Seed worker adapter. Reuse native 48kHz capture and managed sink/gates; no Torch import in the application and no plugin framework.

**Tech Stack:** Python 3.11/uv/pytest, existing PipeWire helpers, React/Tauri, optional isolated Seed runtime.

**Spec:** ../specs/2026-10-28-direct-vc-product-design.md

## Global Constraints

- Initial/restarted direct output OFF; explicit source identity and Start required.
- Existing start payload without mode means passthrough; invalid mode never falls back.
- No new downloads or physical recording. Existing consented Seed assets/reference only.
- Fixed low profile: 80ms blocks, 20ms right context, 10 steps; buffer one unsent block.
- Warmup timeout 60s; running packet timeout 1s; end-of-input-block age at most 160ms including writes.
- VC-only stop/failure leaves ASR/TTS independent; global mute remains upper gate.
- Windows deferred; no publication, upstream contact, PR or AIT runtime modification.

## Review Focus

- An old worker exits after a new Start request: it cannot alter or emit into the new session (Tasks 1/2).
- Source/output with the same name is recreated: identity mismatch fails closed, never silently reconnects (Tasks 2/4).
- Worker says ready but returns original/bypass or malformed silence: ready is not conversion proof (Tasks 2/4).
- Stop arrives while model loading or a pipe write blocks: bounded cleanup, no late unmute, no surviving capture (Tasks 1/2/4).
- Translation and global mute change while VC is active: preserve direct/TTS policy, no unintended raw fallback (Tasks 3/4).

### Task 1: Exclusive direct-session owner

**Files:** Create `src-python/models/voice_conversion/{__init__,direct_voice}.py`, `tests/voice/test_direct_voice_session.py`.
**Interfaces:** `DirectVoice(passthrough_factory=SourceBridge, converted_factory=None)`; `start(*, source, expected_generation, mode='passthrough', options=None)`, `stop()`, `close(timeout=3)->bool`, `health()->dict`. Backends expose nonblocking `start(source=...)`, `stop()`, `close(timeout)->bool`, `health()`. The converted factory consumes options. Owner adds mode and retains existing health/generation/source fields.

- [x] Write tests: fresh off/no producer; original-to-converted overlap rejected; stop increments generation before delayed work; cleanup still busy rejects restart; failed converted never constructs original; source/invalid mode leaves output closed; returned health cannot mutate owner; close rejects later starts.
- [x] Run `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python python -m pytest tests/voice/test_direct_voice_session.py -q`. Expected: RED for missing owner.
- [x] Implement exclusive ownership with bounded, nonblocking backend operations; do not connect Controller yet.
- [x] Same command plus `tests/voice/test_source_bridge.py`. Expected: PASS. Commit owner slice.

### Task 2: Live external Seed adapter

**Files:** Create `src-python/models/voice_conversion/{protocol,seed_process}.py`, `integrations/seed_vc/live_worker.py`, `tests/voice/test_vc_protocol.py`, `tests/voice/test_seedvc_live.py`.
**Interfaces:** `SeedProcess(options)` implements Task1 backend; options contain explicit runtime root and permitted reference path. PipeWireCapture delivers `CapturedAudio(AudioFrame, timestamp_ns)` to a bounded assembler. Protocol uses length-prefixed JSON metadata plus exact S16 PCM; session/sequence/rate/channels/input timestamp are validated in both directions. Worker imports GPL loader/BlockSession only in the isolated interpreter.

- [x] Write RED tests for partial framing, oversized header/PCM, wrong session/sequence/shape/rate, stale/future timestamps, nonzero VAD silence, bypass/failure/EOF, input overrun, blocked write, stop-before-ready and old output after cancellation. Assert no raw fallback and all owned children reaped.
- [x] Run protocol/adapter tests with the command prefix from Task1. Expected: RED before implementation.
- [x] Implement bounded duplex transport, strict worker handshake, warmup-before-capture, cancelable existing sink writer and endpoint identity supervision. Keep original file-input PoC intact.
- [x] Run protocol/adapter plus existing Seed and capture unit tests. Expected: PASS. Opt-in real low-profile inference with existing synthetic input reports actual processing and silence behavior; no physical capture. Commit tested adapter.

### Task 3: Product Controller and native controls

**Files:** Modify `src-python/{controller,mainloop,config}.py`, `src-ui/logics/voice/useVoice.js`, `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/DirectVoiceSettings.jsx`, en/ja locales; extend `tests/voice/test_direct_voice_controller.py`, `test_direct_voice_ui.py`.
**Interfaces:** Existing `/run/start_direct_voice` accepts optional mode/options; receiver stamps owner generation. Existing stop fast path retained. Runtime/reference settings persist without starting audio; get state carries explicit mode/converted-ready/activity/error.

- [x] Write RED tests for original payload compatibility, converted selection/strict validation, restart-off, mode switch requiring completed Stop, VC failure without fallback, independent ASR/TTS, routing change and stale queued Start.
- [x] Connect owner/adapter and localized experimental UI; no implicit startup, download or final-gate Resume.
- [x] Run Controller/source regressions and browser save/reload/stop cases in a private network namespace. Expected: PASS. Vite and offline native debug builds must pass. Commit connected feature.

### Task 4: Private audio acceptance and report

**Files:** Create `tests/platform/test_native_direct_vc.py`, update completion ledger and a direct-VC product report/results artifact.
**Interfaces:** Existing native WebDriver, private PipeWire and approved Seed fixtures. Reuse synthetic original for independent ASR; do not capture physical mic.

- [ ] Model-free private audio tests assert one producer, no output after Stop/worker failure/identity replacement, preserved endpoint and TTS continuity. Expected: PASS.
- [ ] Opt-in native real Seed tests: explicit Start, actual converted blocks, idle, Stop, same-name input replacement, restart-off; paired ASR/TTS tests are separate from single-engine timing. Expected: PASS or report specific unresolved engine gate.
- [ ] Run standard and voice regressions, native acceptance, Ruff/diff/build. Record exact boundaries, distributions only when enough samples exist, remaining physical/quality/license/Windows gates.
- [x] One independent whole-plan review with available authorized mechanism; one important-finding RED→GREEN fix pass. Commit artifacts and preserve execution handoff for remaining work. See `docs/voice-stack/direct-vc-review-2026-10-28.md`; Task4 remains incomplete because prior intermittent failures are unattributed and same-source ASR/VC coexistence is unverified.
