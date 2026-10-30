# speech.cpp Bundle Artifact Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement inline, task by task. The existing closed-loop authorization applies. Do not use AIT child agents.

**Goal:** Produce a verified, relocatable Linux speech.cpp distribution component without models.

**Architecture:** A build-time Python tool reads a committed release manifest, verifies the exact archive, and copies only the executable plus pinned license notices. The existing external HTTP/Realtime application path is unchanged in this increment.

**Tech Stack:** Python standard library, uv, pytest, official speech.cpp 0.9.0 Linux archives.

**Spec:** [P5-A design](../specs/2026-10-29-speechcpp-bundle-artifact-design.md).

## Global Constraints

- Start implementation after the preceding 30-minute combined-voice run is assessed. Preserve unresolved evidence.
- Version 0.9.0, source 49f022a48bc1c7e797aa64dd08d2d9655baf299e; retain the exact two sizes and hashes in the design.
- No models, reference audio, VC runtime, restricted OCR model, publication, upstream contact or PR.
- No runtime download; build-time network acquisition requires explicit `--download` instead of `--archive`.
- Use `UV_CACHE_DIR=/tmp/vrct-uv-cache` and uv. Tests require neither network nor GPU/models.
- Keep Windows acceptance and application/GUI integration for later increments.

## Review Focus

- A corrupt or incomplete release must never become a completed bundle (Task 1).
- Existing output and symlinked output must survive a failed staging attempt unchanged (Task 1).
- A ZIP entry must not control extraction paths or make a symlink executable (Task 1).
- Missing/corrupt license text must reject staging rather than omit attribution (Task 1).
- A relocated bundle must work without the developer checkout or installed libspeech (Task 2).

### Task 1: Verified bundle staging and acquisition

**Files:**
- Create `tools/speechcpp_bundle.py`.
- Create `docs/voice-stack/speechcpp-bundle-artifacts.json`.
- Create `licenses/speech.cpp/NOTICE.md` and the six exact license files listed in the design.
- Create `tests/voice/test_speechcpp_bundle.py`.

**Interfaces:**
- `load_manifest(path=DEFAULT_MANIFEST) -> dict`: validate schema/version, fixed source, asset keys, URL, sizes/digests and notices before file/network side effects.
- `fetch_archive(asset: dict, destination: Path, *, opener=urlopen) -> Path`: bounded download of the single selected fixed asset, verify before completion, refuse existing destination.
- `stage_bundle(archive: Path, output: Path, asset: dict, *, notice_root=NOTICES) -> dict`: verify archive and pinned notices, create only the reviewed files, write `bundle.json` last, return its metadata.
- `verify_bundle(root: Path) -> dict`: verify the generated inventory, regular-file executable, sizes and hashes; return metadata or raise a sanitized `ValueError` code.
- `main(argv=None) -> None`: CLI `--variant {linux-x64-cpu,linux-x64-vulkan} (--archive PATH | --download) --output PATH`; no arbitrary URL/manifest option.
- `bundle.json` uses schema 1 with component, version, source_commit, variant, archive `{name,size,sha256,url}`, and files `[{path,size,sha256}]` including notices, excluding itself. Paths are fixed relative names only.

- [x] **Step 1: Write failing tests with small in-memory ZIPs and injected download streams.**
  Assert exactly one executable and all notices in successful output; hashes match actual output bytes; no model/header/shared library is copied. Assert bad hash, short/oversized/interrupted download, duplicate/symlink/missing speech, missing/changed notice, existing file/directory/symlink destination all fail without altering pre-existing data. Assert no network when `--archive` is selected and missing source choice fails before work. Add a subprocess `python -O` rejection check. Check committed release identity against the values in the design.
- [x] **Step 2: Run RED.**
  Run `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --offline --no-project --python .venv_linux/bin/python python -m pytest tests/voice/test_speechcpp_bundle.py -q`.
  Expected: import/function failures because the tool does not exist; inspect each failure before implementation.
- [x] **Step 3: Implement the tool and commit fixed metadata/notices.**
  Use streamed SHA256, explicit exceptions, exclusive output creation and cleanup scoped to files created by the current call. Read the single ZIP member; never call extractall or execute downloaded content during staging. Keep all production functions small and avoid a general package manager abstraction.
- [x] **Step 4: Run GREEN plus existing distribution tests.**
  Run the Task 1 test command with `tests/voice/test_config_and_distribution.py tests/voice/test_seedvc_artifacts.py` also selected.
  Expected: all selected tests PASS, no acquisition or model execution.
- [x] **Step 5: Commit this independently testable build-time component.**
  Commit only the files named in Task 1, with message `feat(packaging): stage pinned speech.cpp with license notices`.

### Task 2: Real archive relocation and evidence

**Files:**
- Create `docs/voice-stack/speechcpp-bundle-report.md`.
- Update `docs/voice-stack/licensing.md` and `docs/voice-stack/completion-ledger.md`.
- Generated archives, components and command output stay in ignored `tmp/voice-resume/speech-bundle/`.

**Interfaces:** Consumes Task 1 CLI and `verify_bundle`; records independent CPU/Vulkan results. No new runtime API.

- [x] **Step 1: Obtain the two fixed official archives through the CLI's explicit download mode.**
  Run each variant with a distinct empty output path under the ignored directory.
  Expected: exact expected archive size/hash and complete staged inventory, or a diagnosed failure. The user already approved binary bundling; this does not authorize new model acquisition.
- [x] **Step 2: Check relocation and dynamic dependencies.**
  Copy each complete component to a fresh temporary directory, verify its inventory, run `speech --version` with a fresh HOME and empty cwd/LD_LIBRARY_PATH, and inspect `readelf -d`/version requirements. Check no user/model cache was created. Run `tools/check_voice_distribution.py` against both component roots.
  Expected: speech version0.9.0; no dependence on bundled libspeech or checkout; Vulkan depends on OS loader, CPU does not. Keep unexpected RUNPATH recorded, and fail if relocation needs its absolute path.
- [x] **Step 3: Record results and limits.**
  Include actual hashes, files/bytes, original notices, command exits, tested OS and source links. Distinguish build-time component success from pending GUI ownership, complete app packaging, other distributions and Windows acceptance.
- [x] **Step 4: Review the entire increment against the spec and rerun affected checks only if corrections were needed.**
  No P5 external-code review transmission is authorized by the earlier P2/P4 approvals; perform the local review inline. Security scanning with Trail of Bits remains a later pre-publication gate.
- [x] **Step 5: Commit evidence and update the parent plan/ledger.**
  Commit `docs: record verified speech.cpp bundle component`; continue with a focused owned-server lifecycle design. Do not publish or contact upstream.
