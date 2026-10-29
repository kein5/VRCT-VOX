# Linux Build Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Produce and validate a relocatable Linux x86_64 candidate through one uv-driven local/CI build entry.
**Architecture:** Linux-only PyInstaller onedir + isolated Tauri build workspace. Immutable resources and XDG mutable state are separated; fixed speech.cpp stays model-free.
**Tech Stack:** Python 3.11/uv/PyInstaller, Rust/Tauri, Vite/npm, C/PipeWire, GitHub Actions.
**Spec:** `docs/superpowers/specs/2026-10-29-linux-build-pipeline-design.md`

## Global Constraints

- No publish/push/tag/AUR/upstream contact or model acquisition; preserve notices and Windows/development paths.
- Pipeline outputs tar.gz + sha256 + inventory. Runtime kernel PIDFD_THREAD requirement remains Linux >=6.9.
- CI Ubuntu 24.04 x86_64; do not claim older glibc portability from local build success.
- Runtime helper/controller behavior and audio deadlines remain unchanged.
- Model-free tests use synthetic data and private audio graphs; GUI uses DPMS guard.

## Review Focus

- Read-only install directory: config/log/models write only to user state.
- Frozen paths: helpers, fonts, prompts and external VC adapter modules resolve after relocation.
- Native ABI pollution: external tools must not inherit PyInstaller's library override.
- Archive links: internal links preserved; outside/broken/cyclic paths rejected.
- Partial builds: no dev-sidecar fallback or artifact published after failed inspection.

### Task 1: Runtime paths for an immutable installation

**Files:** new `src-python/runtime_paths.py`, `tests/voice/test_runtime_paths.py`; modify config/model/mainloop,
audio_routing/speech_server/voice_conversion/capture helper paths, Rust startup log path.
**Interfaces:** `resource_root() -> Path`, `bootstrap_linux_frozen()`, `external_process_env() -> dict`;
`Config.PATH_DATA` retains PATH_LOCAL for development/Windows, uses VRCT_DATA_DIR for frozen Linux.

- [x] RED: relocated `_MEIPASS`, XDG/explicit override, no source/Windows mutation, external LD_LIBRARY restoration.
- [x] Implement pure path helpers and frozen bootstrap; move only mutable model/cache usages.
- [x] Connect native resource/child environment lookups and Rust log path.
- [x] GREEN: path tests, affected helper/Config contracts, standard regression. Commit.

### Task 2: Freeze and assemble Linux candidate

**Files:** new `spec/backend_linux.spec`, `requirements-linux-build.in/.lock`, `tools/build_linux.py`,
`tools/linux_package.py`, `tests/voice/test_linux_package.py`; extend native helper build output option and distribution guard's explicit internal-link mode.
**Interfaces:** builder CLI selects work/output, Python, speech variant/archive; stage resources, freeze, isolated Tauri build;
package tool validates final tree/tar, emits inventory and SHA-256.

- [ ] RED: bounded collector, forbidden models, source symlink escape, broken/cyclic links, tar traversal/duplicates, missing runtime components.
- [ ] Compile Linux dependency lock using uv; include only fixed resource paths and metadata/notices in spec.
- [ ] Implement pipeline with checked subprocess failures and isolated Tauri workspace; avoid Windows batch commands.
- [ ] Build actual local candidate, inspect ELF/resources/tar, run relocated frozen stdio smoke. Investigate failures with imozuru.
- [ ] GREEN: package tests and real build/smoke. Commit.

### Task 3: CI and native acceptance

**Files:** new `.github/workflows/build-linux.yml`, `tests/platform/test_linux_package.py`,
`docs/voice-stack/linux-build-pipeline.md`; update completion ledger/README/package proposal.
**Interfaces:** workflow invokes same builder, verifies checksum/policy and headless/Xvfb smoke, uploads only successful candidates with contents:read.

- [ ] Add model-free relocated frozen/GUI acceptance (explicit opt-in locally), synthetic graph and read-only installation.
- [ ] Wire CI system dependencies, uv lock sync, npm ci, locked Cargo and artifact inspection; no publisher/secrets.
- [ ] Run local native acceptance with DPMS guard, relevant full regression/build checks. Record CI not run unless actually observed.
- [ ] Review complete diff, fix critical/important findings with RED→GREEN; document remaining license/security/OS gates. Commit report.
