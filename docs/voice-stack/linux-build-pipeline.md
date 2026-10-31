# Linux build pipeline

`tools/build_linux.py` builds an **unpublished x86_64 candidate**: frozen Python sidecar,
Tauri frontend, four C audio helpers and pinned speech.cpp 0.10.0 CPU or Vulkan.
The default output is a `tar.gz`, SHA-256 sidecar and JSON file inventory. Use tar with symlink
preservation; copying only the executable or flattening `_internal` is unsupported.
Add `--appimage --download-appimage-tools` for an additional inspected AppImage;
see [AppImage build and acceptance](appimage.md). The CI builds both formats.

The GitHub Actions workflow `VRCT-VOX Linux candidate (no publication)` targets Ubuntu 24.04.
It runs on relevant pull requests or manual dispatch, tests the relocated package,
and the AppImage extraction fallback, then retains successful candidates for seven days. It has `contents: read`, no
publishing credentials and no release/AUR/upstream actions. Creating the workflow
does not mean a hosted run has already passed.

## Build locally

Use Linux x86_64, Python 3.11 via uv, Node/npm, Rust/Cargo, a C compiler and pkg-config.
Ubuntu build/runtime prerequisites (see the workflow for GUI-test dependencies):

```sh
sudo apt-get install build-essential pkg-config binutils libwebkit2gtk-4.1-dev \
  libssl-dev libxdo-dev libayatana-appindicator3-dev librsvg2-dev \
  libpipewire-0.3-dev pipewire-bin libvulkan1 libglfw3 libportaudio2 libasound2-dev \
  meson ninja-build libsndfile1-dev libglib2.0-dev liblua5.4-dev
mkdir -p build
bash tools/ci/setup_pipewire.sh "$PWD/build/ci-audio"
while IFS= read -r setting; do export "$setting"; done < build/ci-audio/environment
export PATH="$PWD/build/ci-audio/prefix/bin:$PATH"
uv run --no-project --python 3.11 python tools/build_linux.py \
  --python 3.11 --variant linux-x64-vulkan --download-speech
```

The native capture helper uses the clock API tested with PipeWire **1.6.10**.
Ubuntu 24.04's stock headers lack the cycle and discontinuity fields; its stock
packages alone cannot build this helper. Both Linux workflows build the pinned
PipeWire 1.6.10 and WirePlumber 0.5.18 sources in a new, isolated prefix after
checking SHA-256. Headers, client libraries, tools, modules and configuration are
selected together. The script never installs or starts system services and
refuses an existing destination. WirePlumber 0.5 supplies the policy-only profile
used by private synthetic tests; that is not compatible with Ubuntu's 0.4 CLI.
Hosts with the already tested versions can use their system installation instead.
The capture helper requires headers, the linked client library and the connected
daemon to report PipeWire 1.6.10 or newer. It rejects older/malformed runtime versions
before emitting PCM; compile-time checks give an explicit dependency error. This
does not relax timestamp/discontinuity checks or validate every newer release.

`--download-speech` authorizes acquisition of **only the pinned engine executable**.
Alternatively use `--speech-archive /absolute/path/speech-0.10.0-linux-x64-vulkan.zip`;
the archive and executable hashes are checked against `speechcpp-bundle-artifacts.json`.
Choose `--variant linux-x64-cpu` with the corresponding CPU archive for CPU builds.
`--offline` requires uv, npm and Cargo caches to be populated. No engine models or
reference recordings are fetched. `--backend-only` is a diagnostic mode and produces
no distributable. `--profile debug` is also diagnostic; normal output is release.

The builder syncs `requirements-linux-build.lock` into `build/linux/venv`, uses
`npm ci --ignore-scripts`, and builds Cargo with `--locked` in a copied workspace.
It does not replace `src-tauri/bin` or reuse its development Python wrapper.
Python packages are exact versions and Git dependencies are full commits; this is
**not** a claim of bit-for-bit reproducible builds or a fully hash-locked wheel set.
Rust, system libraries and actual ELF version requirements remain host dependent.
The inventory records the build commit, tracked dirty state, host, hashes and ELF versions.

Default outputs:

```text
build/linux/artifacts/VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz
build/linux/artifacts/VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz.sha256
build/linux/artifacts/VRCT-VOX-<version>-linux-x64-vulkan-release.manifest.json
```

## Run and inspect

```sh
cd build/linux/artifacts
sha256sum -c ./*.tar.gz.sha256
# Inspect with tools/linux_package.py before extracting an independently obtained candidate.
tar -xzf VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz
./VRCT-VOX/vrct-vox
```

The full `VRCT-VOX` directory must stay together. The host supplies WebKitGTK 4.1,
GTK3, OpenSSL, PipeWire/tools, Vulkan loader for Vulkan variants and other system
ELF dependencies. This is a portable directory layout, **not** an AppImage or a
promise of compatibility with all distributions. A build made on CachyOS may
require newer glibc than the Ubuntu CI build; consult its manifest.

Frozen Linux settings/logs go to `$XDG_CONFIG_HOME/vrct-tts` (default `~/.config/vrct-tts`),
weights and other writable data to `$XDG_DATA_HOME/vrct-tts` (default `~/.local/share/vrct-tts`),
and caches to `$XDG_CACHE_HOME/vrct-tts` (default `~/.cache/vrct-tts`). Explicit
`VRCT_CONFIG_DIR`, `VRCT_DATA_DIR`, `VRCT_CACHE_DIR` override those directories.
An explicitly supplied `HF_HOME` is respected. Existing development/Windows paths are unchanged.

Managed audio still needs the explicit PipeWire setup in `local-setup-linux.md`.
The package carries the template at `_internal/config/pipewire/90-vrct-managed.conf`;
it does not install it or restart the user's audio service. Owned audio workers
require Linux >=6.9 (`PIDFD_THREAD`), in addition to a supported PipeWire runtime.
RVC/Seed-VC inference environments and user models remain external selections.

## Acceptance and exclusions

```sh
VRCT_TEST_LINUX_ARCHIVE=/absolute/path/candidate.tar.gz \
  uv run --no-project --python build/linux/venv/bin/python python -m pytest \
  -c tests/voice/pytest.ini tests/platform/test_linux_package.py -q
```

This extracts to a path containing spaces, makes the installation read-only,
checks restart/settings persistence, the frozen router and bundled engine entry,
and verifies installation hashes did not change. For GUI tests also set
`VRCT_TEST_NATIVE_GUI=1` and `VRCT_TEST_DRIVER` to a tauri-driver 2.1.0 executable.
On a physical desktop run under `tools/display_power_guard.py` via system Python/Gio.
CI explicitly uses `VRCT_TEST_XVFB=1` with Xvfb, checks its server and real rendering.
Setting `VRCT_TEST_NATIVE_ROUTE=1` additionally tests a private PipeWire graph and
managed mute/resume/restart (requires WirePlumber 0.5's policy profile). This is a
local acceptance option; Ubuntu 24.04 CI runs the remaining smoke cases and does
not claim audio-graph acceptance. None of these tests record the physical microphone,
contact VRChat, or load inference models.

The collector and final tree/tar checks reject OCR weights, Mia2026 assets, unsafe
links, traversal, duplicate paths, special files and uninspectable nested archives.
These are path/type checks, not a detector for deliberately renamed weights.
Original licenses and notices are retained. Available Python package notices and
the environment inventory are in `_internal/licenses/python` and
`_internal/python-environment.json`; some packages do not supply license text.
The existing faster-whisper dependency includes its two Silero v5 VAD ONNX assets;
they are dependency resources, not new speech.cpp/RVC/Seed-VC models. They remain
explicitly subject to the final attribution audit. OCR weights are excluded regardless.

## Remaining release gates

- Hosted Ubuntu workflow and clean-distribution runtime acceptance must actually run.
- All bundled native/Python/Rust/frontend components need a completed license/SBOM
  audit, including GPL/LGPL corresponding-source/relink obligations, and the
  user-requested Trail of Bits Skills security review. Collected notices alone
  are not redistribution clearance.
- Real model, listening quality, physical latency, Windows and cross-distribution
  tests retain their existing acceptance status; these smoke tests do not replace them.
- AUR needs a real approved release URL/hash, PKGBUILD/.SRCINFO, clean-chroot and
  install/update/remove tests. No AUR submission or upstream PR is performed here.

## Primary evidence

- [PyInstaller symlink and external-process requirements](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)
  justify tar.gz and restoration of `LD_LIBRARY_PATH` for system tools/external workers.
- [Tauri Linux prerequisites](https://v2.tauri.app/start/prerequisites/#linux) define the
  native WebKitGTK build boundary; [official WebDriver CI](https://v2.tauri.app/develop/tests/webdriver/ci/)
  uses a virtual display on Linux.
- Local imozuru source map/log: `tmp/voice-resume/research/linux-build-pipeline/`.
  Behavioral evidence and unresolved platform limits are recorded separately from documentation claims.
