# VRCT-VOX integration implementation plan

> For agentic workers: execute this plan in the existing worktree; reuse the existing reviewer only. Do not create new agents.

**Goal:** Finish the requested rename, full dark-studio UI, developer tooling, distribution pipeline and develop integration.

**Architecture:** Retain React 18/Jotai/CSS modules, Tauri and Python contracts. Shared tokens and common controls carry the redesign. Build and test commands are shared between local development and CI. Preserve data/storage identities.

**Tech Stack:** React 18, Vite, SCSS, Tauri 2, Python 3.11, uv, Cargo, GitHub Actions, Cocogitto.

**Spec:** PRODUCT.md, DESIGN.md, docs/voice-stack/project-rename.md.

## Global constraints

- User approved full-app redesign and dark navy/blue direction; component details are implementation decisions.
- Preserve pre-existing edits, history, licensed notices, model consent, config paths and audio behavior.
- Japanese prose uses yomiyasu; supporting skills and primary-source research are recorded.
- No new agents, host audio-service restart, automatic release publication or upstream contact.

## Tasks

- [x] Rename repository, product/binaries, URLs, packaging and README; run identity/storage/package tests.
- [x] Replace shared palette and app-shell/control layouts; add keyboard labels, empty state and reduced motion.
- [x] Inspect representative real component renders and run existing browser voice/model/Quick Chat regressions.
- [x] Add EditorConfig, Cocogitto and cross-platform setup/doctor/check commands with owned-file tests (existing reviewer).
- [x] Align CI and candidate provenance/checksums, prepare explicit publication path with tested-artifact validation.
- [x] Build the renamed AppImage, run native UI/sidecar checks with isolated config and verify packaged names.
- [ ] Review all pending changes, commit coherent work, merge into current develop without rewriting history, and verify remote result.

## Review focus

1. Long Japanese labels and paths at narrow sizes; keyboard navigation and popup clipping.
2. TTS/RVC enable, mute, save and model consent remain separate and unchanged.
3. New branding does not orphan config, model cache or virtual microphone ownership.
4. Test failures distinguish environmental access, test isolation and real regressions.
5. Public commits/candidates exclude local credentials, model weights and private test audio; old measured evidence keeps its identity.
