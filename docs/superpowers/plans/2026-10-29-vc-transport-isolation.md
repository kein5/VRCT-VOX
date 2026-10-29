# VC Transport Isolation Implementation Plan

> Execute inline with superpowers:executing-plans; no AIT delegation.

**Goal:** Prevent application GC from stopping the direct VC audio transport.
**Architecture:** Fixed child transport reuses existing VCProcess; bounded
configuration/health pipes, native creator-thread lifetime supervision.
**Tech stack:** Python/uv, Linux C supervisor, existing PipeWire helpers.
**Spec:** `docs/superpowers/specs/2026-10-29-vc-transport-isolation.md`.

## Constraints and review focus

No new models, recording, upstream contact or release. Preserve one queued
block/160 ms deadline. Malformed/oversized/stale IPC, Stop during loading,
parent/thread/supervisor exit, failed cleanup and frozen startup must fail closed.

## Task 1: Isolated owner and protocol

Files: models/voice_conversion/{isolated,router_worker,direct_voice}.py,
native/vc-worker/main.c, src-python/mainloop.py, tests/voice and tests/platform.
Interface: IsolatedVCProcess exposes existing start/stop/close/health; child
creates the engine-specific VCProcess. Only fixed router entry points accepted.

- [ ] Add a forced parent GIL-pause regression; observe current product RED.
- [ ] Add strict control-frame and supervisor fixed-entry/lifetime tests, RED.
- [ ] Implement owner/worker and frozen early entry, GREEN; keep direct settings.
- [ ] Verify Stop, failure, malformed IPC and all native supervisor variants.
- [ ] Review P2 change through already-authorized standalone read-only CLI.
- [ ] Commit and resume combined native/30-minute validation plan.
