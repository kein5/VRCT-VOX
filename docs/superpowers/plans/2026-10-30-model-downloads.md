# Settings model downloads

Authorized scope: fixed Hugging Face defaults for Irodori, Qwen and a licensed RVC voice; explicit per-download warning and consent; offline tests. No model execution, GPU/audio operations, builds or commits. Existing edits and the parallel low-latency implementation are retained.

Use an independent download manager and UI. Existing translation startup consent remains separate. A fixed catalog is preferable to arbitrary URLs (no reviewable artifact identity) or delegating to model loaders (network/load side effects). The UI shows author, model, exact bytes, immutable source, licenses, purpose, restrictions and destination before a checked consent and Start. Completion exposes a separate Apply model path action; download completion never starts a server, microphone or voice conversion.

One worker downloads at a time. Fixed repository/revision/file/SHA256 and sizes; HTTPS with bounded approved redirects, bounded reads, no executable deserialization, fresh private staging files, streaming hash, exact length, cancellation, free-space preflight, atomic publication. A bad existing cache is retained and reported. Retrying revalidates completed cache. No partial files are selected as settings. State uses monotonically ordered observations and job identities; cancellation/Apply cannot target a later job. Shutdown cancels its worker. Applying checks the verified files and current expected paths, preserves unrelated settings (including low_latency), and refuses an active target or stale settings.

RVC is only a voice artifact, not a runtime installer. Show the separate engine, Python environment, HuBERT and RMVPE requirements. Never load a .pth to inspect it. Primary-source research and candidate exclusions are in tmp/model-download-research; the checked-in evidence summary will record immutable links and hashes.

1. Record pinned candidates and terms, including RVC provenance and runtime limits.
2. RED/GREEN manager tests for consent, corrupt/truncated/oversized data, cancellation, space failure, existing cache, symlinks, identity and Apply.
3. Controller/stdio integration with overlay deny verification and no activation side effects.
4. Independent ModelDownloads UI, minimal parent inserts, translations and offline browser tests for consent, progress/cancel/failure/Apply and dirty settings.
5. Relevant regression tests, frontend build without app launch, report code paths/results/limits to the parent.
