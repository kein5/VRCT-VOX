# Seed-VC PoCの判断と保留事項

実装・独立レビューの判断を時系列で記録。製品採用の承認ではない。

- Ruling: scoped external GPL adapter before product converted mode; no claim allP2 complete. Cost: later integration and distribution-license work remains.
- Ruling: keep execution evidence/worktree during user-requested continuous work. Cost: local disk usage.
- Ruling: GPU query in restricted sandbox failed; host query confirms RTX4080SUPER16GB driver615.78.08. No driver fault inferred, no system changes. Existing .venv_linux lacks torch; expected external PoC env will install it.
- Task 2: Ruling: runtime selection follows official torch2.10/audio2.10/vision0.25 CUDA12.8 combination; replaces incompatible upstream torch2.4+cu128. Two confirmed weights_only advisories set 2.10 minimum, not a full dependency security audit. Cost: newer runtime needs real regression validation.
- Task 2: Ruling: failure/bypass/stop gate tests belong with actual block worker in Task3; Task2 only returns a fully loaded engine, never converted status. Avoid premature coordinator. Cost: no live conversion claim until Task3.
- Task 2: Ruling: strict actual Seed load found missing freqs and position shape mismatch. imozuru fixed-source/history and real artifact confirm deterministic buffers: regenerate missing float32 frequencies, validate int64 arange(8192) then expand to runtime arange(16384). All learned weights remain complete/strict. Cost: numerical/quality parity still needs real conversion testing.
- Task3: Ruling: two imozuru roles found fixed engine wipes idle VAD cache each block, preventing accumulation of 150ms onset evidence. Actual180/20 and80/20 profiles both all-silent RED; remove only idle reset, retain10s wall-clock periodic reset and explicit prepare. Both actualprofilesGREEN18.34s; this is a corrected upstream behavior, not merely instrumentation. Cost: long-duration VAD/reset and perceptual onset quality still unverified.
- Task3: Ruling: native2block ring-priming formula does not apply to direct _process_block worker. All source-onset→capture values derive from real-time file release plus OS read timestamps. Native-ring prediction must not be presented as explanation of measured2.5s.
- Task3: Ruling: prime only a private OS source that accepts this supervisor's verified converted/silence PCM; it emits nothing before BlockSession validation. OS route activity remains separate from conversion. This reduces first-speech connection cost without relaxing inference checks. Cost: does not authorize arbitrary external source/bypass; production capability/identity integration remains required.
- Task3: Ruling: simple1760Hz decoy detector also fires briefly on converted harmonics; report does not claim zero in-voice contamination. Post-stop windows remain silent and identity/fallback has separate SourceBridge evidence. Cost: speech-time contamination/word-onset/perceptual quality remain separate tests.
- Final: minor (deferred): baseline markdown 36.82/38.43ms and JSON37.36/39.21ms are separate runs without explicit labels; do not compare as one run.
- Final: minor (deferred): one-second next-packet timer begins before caller starts input; unusually slow private-route setup may falsely close an idle worker.
- Final: Ruling: production Controller/UI converted integration is outside this scoped PoC and remains disabled — route health cannot claim conversion — cost: P2 still needs product integration.
- Final: Ruling: physical mic/VRChat/Windows/hotplug are not covered by this private file-source test — keep them as required acceptance gates — cost: device behavior remains unknown.
- Final: Ruling: physical latency targets and engine adoption remain unproven — retain Seed only as candidate — cost: this work may need replacement if targets fail.
- Final: Ruling: perceptual quality, onset retention and noise require a separate quality gate — finite converted PCM is insufficient — cost: no usability guarantee yet.
- Final: Ruling: long VAD reset and GPU contention are untested by short trials — extend trials before product defaults — cost: potential intermittent dropout/overload.
- Final: Ruling: in-voice 1760Hz hits cannot distinguish converted harmonics from decoy — use post-stop/identity evidence only — cost: acoustic contamination during speech remains unmeasured.
- Final: Ruling: final distribution licensing and full dependency security audit are release gates — segregated GPL adapter/model is not a license exemption — cost: release may require source/notice or packaging changes.
- Final: Ruling: arbitrary malicious engine checkout replacement or concurrent file mutation is outside the fixed local trusted checkout boundary — hashes validate declared artifacts at load — cost: compromised local runtime is not defended by this PoC.
- Final: Ruling: BlockSession inference is single-worker-thread only; stop may race and is tested — do not imply parallel convert support — cost: future multithread use must serialize or redesign.
