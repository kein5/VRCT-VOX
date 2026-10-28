# P2 RVC integration: model-free implementation boundary

User decision (2026-10-29): integrate RVC into P2; no RVC model is installed, so implement and test without model acquisition first. Existing authorization permits inline implementation and local commits. Do not contact upstream or publish.

## Decision

Retain architecture B: an external inference process and the existing OS audio route. Share the bounded capture/worker/output owner between Seed-VC and RVC. Add a fixed RVC worker, not a general plugin host. ASR still sees original input, and OSC/TTS remain independent. Original and converted direct input are mutually exclusive.

Alternatives: embedding Torch in the sidecar increases dependency and crash coupling; running an RVC GUI with its own audio output bypasses VRCT's stop and mute guarantees. Both are rejected for this slice. Reconsider the GUI route only after proving ownership and bounded shutdown through a documented API.

Saved settings add `engine` (`seed-vc` default or `rvc`), `rvc_runtime`, `rvc_model`, `rvc_index`, `rvc_pitch` (integer -24..24), `rvc_index_rate` (finite 0..1). Keep Seed `runtime`/`reference` and old start requests compatible. RVC Start requires local runtime and `.pth`; `.index` is optional, but required for nonzero index rate. No download, capture, or inference occurs on Save. Changing engine requires Stop.

The Linux process uses the existing fixed native supervisor and creator-thread pidfd. The RVC branch launches only `integrations.rvc.live_worker`. Worker readiness identifies the expected engine. Preserve 48 kHz mono S16, 80 ms blocks, one unsent complete block, maximum 160 ms age after block end, cancellation-atomic OS writes and no original fallback. Windows remains deferred and must not import Linux-only backends on startup.

RVC source is pinned to RVC-Project/Retrieval-based-Voice-Conversion-WebUI commit `81eed5e8f68b6bed1789f682fe78cdd324495afc`. A separate runtime owns Torch and the source checkout. Load local HuBERT, RMVPE and the permitted speaker checkpoint only; enforce weights-only checkpoint loading and offline transformer loading. First profile uses RMVPE, speaker 0, formant 0, 80 ms input, 40 ms SOLA overlap, 10 ms search and 2 s history. CUDA graphs stay off until real-model validation. Model versions v1/v2 and sample rates 32/40/48 kHz are the intended checked formats. Unsupported/partially initialized engines and failed requested retrieval must fail closed.

Port only the upstream streaming ring, resampling and SOLA overlap logic; do not import the upstream GUI/audio callback. Warm up before readiness and reset history after warmup. Synthetic fake inference proves framing and lifecycle only, never voice quality or real-time feasibility. No latency target is reported as measured performance.

## Evidence and licensing

Primary sources: [RVC README](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/docs/en/README.en.md), [RVC inference](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/infer/rtrvc.py), [streaming GUI algorithm](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/realtime_gui.py), [Seed README](https://github.com/Plachtaa/seed-vc).

RVC normally uses a speaker-specific trained `.pth` and optional retrieval `.index`; using someone else's permitted pretrained model does not require training. Seed uses a short reference recording without speaker-specific training. Both change the voice of speech, not its language. RVC source is MIT and the current Seed integration is GPL-3.0-only; dependencies and weights require separate license review. Preserve upstream MIT notice for adapted streaming logic. Do not assume a model's permission from the engine's license.

imozuru trace: `tmp/voice-resume/research/p2-rvc-integration/{map.md,log.md,sources}`. Followed README to inference, GUI, HuBERT, RMVPE and CUDA-graph implementations. Notable evidence: RVC initialization and index lookup can swallow exceptions; successful construction alone is insufficient. HuBERT defaults to a source-relative asset directory and must be explicitly redirected to the local runtime assets.

## Acceptance and remaining work

Model-free acceptance: old Seed settings/start compatibility; RVC settings round trip; wrong engine handshake rejected; bounded late/stale/EOF/bypass behavior; Stop and owner-death cleanup; GUI selection/save/start; fake-engine streaming frame shape, finite values, overlap history and failure handling; no automatic downloads.

Real-model acceptance remains open: runtime dependency installation/lock, HuBERT/RMVPE provenance and consent, target model permission, native private-route output, listening, actual inference and end-to-end latency distributions, GPU contention and endurance. Existing Seed intermittent expiry/capture failures remain unresolved and are not superseded by RVC tests.
