# Realtime microphone translated speech

Basis: user implementation spec §4/§5/P4, approved architecture B, and the user's 2026-10-28 instruction to continue the proposed P4 work. Continuous inline execution and routine design choices are authorized; no repeated approval gate. Model downloads still require the separate §8 consent.

## Intent and constraints

Realtime microphone **finals** may produce the selected successful translation as speech. Partials, speaker/OCR/WebSocket receive events, failed translations, disabled targets and stale work never produce microphone audio. Default remains OFF. Keep P1 chat behavior and legacy payload contracts. Keep inference external, bounded queues, source-specific stop and explicit OS routing; no new audio capture during validation, use existing synthetic fixtures and a private PipeWire graph.

## User-confirmed final-only translation policy (2026-10-28)

After comparing the fork baseline's cumulative interim recognition and translation/OSC path with the new Realtime path, the user explicitly chose the new path: partials update original-language captions; finals enter translation, and only the selected successful final translation may enter TTS. Microphone OSC remains conditional on its existing send setting. This prioritizes consistency between the translated text and spoken content over starting translation or speech from an unstable interim transcript. Translated captions, OSC and TTS consequently wait for final recognition; this is not a claim of lower end-to-end latency or guaranteed recognition/translation accuracy. Existing legacy behavior remains available. Revisit interim translation only if the user requests a different behavior; it must not silently enable interim speech.

## Approaches

1. Extend the existing single TTS worker and managed router (chosen engineering decision): one serialization/cancellation boundary, common model routing and output ownership. Requires separate mic cancellation and scheduling policy.
2. A separate mic TTS worker: superficially smaller hookup, but two output owners can overlap and require a second arbitration layer. Rejected.
3. Move translation and audio scheduling into a new sidecar: stronger isolation but duplicates existing translation/config/IPC and adds deployment work without measured benefit. Rejected.

## Settings and scheduling

Add string fields `mic_mode=off|translated` (default off) and `direct_policy=suppress|mix` (default suppress) to existing VoiceSettings. Chat `mode` remains independent. Both use existing target_slot and Japanese/multilingual servers. Mic translated + suppress requires managed routing; external routing requires the explicit mix choice. UI explains that managed suppression controls only the managed direct branch and that changing the routing policy requires explicit Resume. Settings do not start ASR, install models, or connect an external VC engine.

VoiceEventBus accepts only final chat or explicitly enabled mic events. Mic requests always use translated text and never fall back to original. Deduplicate by source + namespaced utterance ID. One worker, total queue bound 4, chat before queued mic (no interruption of an already playing utterance). On overflow evict oldest mic first; a new mic cannot evict chat-only pending work. Existing chat-only oldest-drop behavior remains.

Keep global generation for mute/stop/configuration, add per-source generation and `cancel_source('mic')` to drop/cancel only microphone speech. Snapshot generations and voice settings **before** translation. Preserve received_ns as final receipt time (not physical microphone onset). Mic speech must start within 5 seconds of that receipt; queue and initial inference count. Initial-start expiry must not truncate a valid utterance after playback begins. Existing total request timeout 30 seconds remains. Queue policy and exact deadlines are engineering defaults, not measured performance.

## Pipeline hookup

Pass trusted TranscriptUpdate only from the Realtime mic callback into the existing pipeline. Preserve word filtering and translation results. Publish only after the existing publication guard passes, selected target still matches the snapshot, and its translation success flag is true. No speaker path can supply this capability. Use selected enabled-target order, not arbitrary payload position. Stop/settings invalidation and natural session termination cancel mic speech; delayed old-owner termination cannot cancel a newer session. No callback that takes Controller locks is invoked while the bus lock is held.

## OS audio exclusion

Extend the existing identity-bound native gate with one allowlisted target, managed VC sink; keep existing source and owned source-bridge modes. Do not accept arbitrary node names. Inspect main and direct branch identities/mute values from one graph snapshot. Managed VoiceRoute owns both desired states. On mode/policy changes, reconnect, branch identity change or unexpected branch mute drift: mute software and main source, verify direct suppression policy, retain global mute until explicit Resume. Resume only after both observations and durable global intent are valid. Branch control failure attempts to close the main gate and reports unconfirmed state rather than claiming silence. SourceBridge can remain connected; only its managed output branch is suppressed. TTS branch stays available under global Resume.

## Validation and limitations

- Unit/HTTP tests: final-only, once, selected slot/language, translation failure, off/partial/remote exclusion, source stop during HTTP/playback/blocked translation, deadline before first sample, sustained speech after start, queue priority/overflow, configuration races, P1 compatibility.
- Private OS test: continuous distinguishable synthetic direct tone plus TTS; suppression removes only direct tone; explicit mix restores it; policy switch, identity replacement and gate failure do not claim ready or silently resume.
- UI/Controller test: persist choices without capture, enable/disable and explicit Resume, source stop does not cancel chat, error codes shown without text disclosure.
- Actual ASR/translation/TTS native acceptance and timing: reuse approved models first; a fixed HTTP translation is only integration evidence, not real MT quality/performance. Additional multilingual weights require consent. No physical or VRChat/HMD latency claim from private routing.
- Windows native capture/control, VC quality and mixed-load performance remain separately visible gates. No upstream contact, push, publication, or PR.

Research in progress: tmp/voice-resume/research/p4-spoken-translation/. Local implementation inspection confirms branch mute is missing; official source findings will be recorded before native changes.
