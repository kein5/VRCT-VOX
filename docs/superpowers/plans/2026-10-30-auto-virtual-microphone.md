# Automatic virtual microphone implementation plan

> Execute inline using superpowers:executing-plans and test-driven-development. Existing reviewer only; do not create agents.

**Goal:** Managed route selection prepares the Linux virtual microphone automatically.
**Architecture:** Host pw-loopback user services, provisioned by an idempotent Python control component and verified through the existing PipeWire gate.
**Tech Stack:** Python, systemd user manager, PipeWire, existing React UI.
**Spec:** `docs/superpowers/specs/2026-10-30-auto-virtual-microphone-design.md`

## Global constraints

Preserve existing changes. No audio service restart, downloads, root install, unrequested microphone capture, commits or publication. Existing manual routes must remain compatible. Never auto-unmute or remove live endpoints on GUI exit.

## Review focus

Concurrent setup, partial/foreign endpoints, foreign service overrides, failed setup followed by retry, closing during setup. Test each in the owning component; isolated native tests verify actual initial mute and persistence beyond control lifetime.

## Task 1: Provisioner

- [ ] Add `tests/voice/test_managed_microphone.py`: existing route reuse, empty graph creation, repeat/concurrent calls, partial owned recovery, foreign files/graph, unavailable manager/tools, failed start and graph timeout. Assert filesystem/graph outcomes, with only OS subprocess boundary substituted.
- [ ] Observe failures, then implement `ManagedMicrophone.ensure(snapshot)` and `service_units(binary)` in `src-python/models/audio_routing/managed_microphone.py`. Fixed service names and commands, process lock, no replacement of foreign files, enabled persistent user services, bounded commands, final graph validation.
- [ ] Run targeted tests.

## Task 2: Route/UI integration

- [ ] Test managed startup prepares asynchronously, errors cannot open software, external route never prepares, closing never provisions; preserve existing gate tests.
- [ ] Add `PipeWireGate.prepare()` and call it on attachment/recovery in `VoiceRoute`, with explicit preparation state. Update Device layout and Japanese/English setup text and error descriptions.
- [ ] Run controller/route/UI regression, Vite build.

## Task 3: Native verification and delivery

- [ ] Add opt-in private PipeWire test for generated commands: graph readiness, initial mute, synthetic PCM, control shutdown retains nodes/mute, idempotence.
- [ ] Verify systemd unit syntax and real user-service control where isolated or safely scoped. Ask existing AIT reviewer for read-only critical review.
- [ ] Update quickstart/ADR/report, build new AppImage and run native startup tests. Report exact tested boundary and remaining limitations.
