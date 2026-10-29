# Combined voice validation and distribution follow-up

User authorized order: real RVC + ASR/final translation/TTS/OSC, sustained mixed
operation, then bundled speech.cpp with managed server controls.

## Constraints and acceptance

- Execute inline in the existing worktree with uv; no AIT child notifications.
- Use the already consented synthetic input, Mia2026 and fixed base models.
  No physical recording, downloads, model redistribution, upstream contact or PR.
- Preserve independent direct audio and caption branches. ASR receives original
  source samples; finals alone enter translation/TTS/OSC. Never raw-fallback on VC failure.
- Fixture translation validates routing, not translation model quality/performance.
- Separate model execution, block-end/write, private PCM and physical/VRChat
  boundaries. Keep Windows, listening and hardware acceptance explicitly open.
- Existing product specs and P2/P4 plans remain authoritative. The following is
  additional acceptance coverage, not a redesign or a relaxed freshness budget.

## Task 1: Real shared-source combined acceptance

- [ ] Extend native product test with real RVC, original-source ASR, fixed HTTP
  translation, Qwen TTS and original+translated OSC on one private PipeWire graph.
- [ ] Verify exactly-once finals and speech, source-specific Stop, global mute,
  independent failure, no raw fallback and muted/no-capture restart.
- [ ] Investigate any failure using imozuru originals and deterministic reproduction;
  change production code only after a meaningful failing regression test.
- [ ] Record measured and unverified boundaries; run affected existing tests.

## Task 2: Sustained mixed operation

- [ ] Run at least 30 minutes with repeated synthetic utterances and real
  RVC/ASR/TTS concurrently; record resource samples, outcomes and bounded queues.
- [ ] Observe Stop and worker failure after the run, with continued source input.
- [ ] Do not call uncontrolled desktop GPU activity a controlled contention test.

## Task 3: Linux bundled speech.cpp

- [ ] Inspect fixed upstream binary/source/license and existing packaging.
- [ ] Write focused design/implementation plan for fixed binary/dependencies,
  model selection, external URL compatibility and owned server lifetime.
- [ ] Implement with RED→GREEN tests, native controls and clean installation checks.
  Models remain separate. Windows binary/native acceptance follows on Windows.

If a preceding acceptance failure remains unresolved after imozuru research,
stop the loop as the user requested and preserve the evidence and remaining work.
