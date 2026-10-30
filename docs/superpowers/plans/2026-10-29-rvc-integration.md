# P2 RVC Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking.

**Goal:** Add a model-free tested RVC choice to the existing direct-voice product path.

**Architecture:** Share the external VC transport and retain separate fixed engine workers. Keep heavy dependencies outside the sidecar and preserve the OS gate.

**Tech Stack:** Python/uv, React, Linux C supervisor, optional Torch/RVC runtime.

**Spec:** `docs/superpowers/specs/2026-10-29-rvc-integration-design.md`

## Global Constraints

- No model acquisition or physical microphone recording; synthetic input only.
- 48 kHz mono S16; 80 ms block; 160 ms maximum age after block end; no raw fallback.
- Existing Seed settings and requests remain valid. No startup capture; engine change requires Stop.
- Windows validation deferred. No upstream contact, PR, push or release.
- Use uv. Execute inline because AIT agent notification failures are unresolved.

## Review Focus

- Legacy partial configuration must normalize without starting anything (Task 1).
- Unknown engine and cross-engine ready packets must fail closed (Task 1).
- Stop during output and owner thread death must reap both worker variants (Task 1).
- Upstream swallowed initialization/retrieval errors must never produce a successful ready/output state (Task 2).
- Unsaved or invalid numeric GUI settings must not start a different producer (Task 3).

### Task 1: Shared transport, settings and fixed RVC process

Files: `src-python/models/voice_conversion/{settings,protocol,process,seed_process,rvc_process,direct_voice}.py`, `src-python/controller.py`, `native/vc-worker/main.c`; tests in `tests/voice/test_{rvc_integration,seedvc_live,vc_settings,vc_worker_native,direct_voice_controller}.py` and `tests/platform/test_native_vc_worker.py`.

Interfaces: `VCProcess(engine=...)` common owner with `_launch_worker()` specialization; `RVCProcess(options)` mirrors Seed start/stop/close/health; `create_converted_process(options)` selects a fixed engine; `ready_info/require_ready(..., engine='seed-vc')` keeps old behavior.

- [x] Write RVC option, migration, factory and handshake tests; parameterize real fake-worker pipe/lifetime tests over engines. Assert missing model fails without capture, stale output is discarded, cleanup completes.
- [x] Run new tests with uv; observe missing feature failures.
- [x] Extract the shared transport without changing its queue/deadline rules; implement strict options and native fixed-module branch.
- [x] Run targeted VC/controller/native-supervisor regression tests; all must pass.
- [x] Commit Task 1.

### Task 2: Offline RVC inference worker and streaming adapter

Files: `integrations/rvc/{__init__,loader,blocks,live_worker}.py`, `integrations/rvc/README.md`, upstream license notice; `tests/voice/test_rvc_worker.py`.

Interfaces: `create_engine(engine_path, assets, model, index, pitch, index_rate)` validates pinned sources/local assets and returns checked RVC; `BlockSession(engine).convert(float32[3840]) -> float32[3840]`; `convert_packet(...)` validates protocol and calls the block session.

- [x] Write fake-engine block/packet tests: exact shape, finite samples, history reset, unsupported model formats, index failure and malformed output; source validation rejects changed/missing checkout or assets.
- [x] Run tests RED before implementing each boundary.
- [x] Implement pinned offline loader and minimal upstream-derived ring/resampling/SOLA; fixed worker warms up then resets before readiness. Include MIT attribution.
- [x] Run model-free tests with available optional Torch interpreter; explicitly distinguish these from a real RVC runtime test.
- [x] Commit Task 2.

### Task 3: GUI engine selection and honest acceptance record

Files: `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/DirectVoiceSettings.jsx`, `locales/{en,ja}.yml`, `tests/voice/test_direct_voice_ui.py`, `docs/voice-stack/{completion-ledger,licensing}.md`, RVC report.

- [x] Add browser checks for RVC fields, persistence, Start payload, disabled edits while active and no automatic Start; observe RED.
- [x] Implement engine-specific controls, complete/dirty validation and translated labels.
- [x] Run browser integration, standard suite, voice regression, optional fake-engine tests and Vite build; record failures/skips honestly.
- [x] Run one read-only independent P2 code review (previously authorized standalone Codex CLI); fix justified findings with RED→GREEN.
- [x] Record model acquisition candidates/conditions, unmeasured quality/latency and open Seed issues; commit Task 3. Do not label real RVC acceptance complete.
