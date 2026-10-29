# Linux AppImage candidate

The Linux builder can also produce an **unpublished x86_64 AppImage** containing
the release GUI, frozen Python sidecar, four audio helpers and pinned speech.cpp.
It deploys GTK/WebKit dependencies before adding the backend, so GUI library
rewriting never changes the inference executable or frozen backend bytes.

## Build

Use the prerequisites in [the Linux build guide](linux-build-pipeline.md), plus
`desktop-file-utils`, `libgtk-3-dev`, `libgdk-pixbuf-2.0-dev` and `glib-networking`
on Ubuntu. Build both formats:

```sh
uv run --no-project --python 3.11 python tools/build_linux.py \
  --python 3.11 --variant linux-x64-vulkan --download-speech \
  --appimage --download-appimage-tools
```

For an existing inspected Linux candidate:

```sh
uv run --no-project --python 3.11 python tools/build_appimage.py --download-tools
```

The second command uses `build/linux/candidate/VRCT-TTS`, `build/appimage` and
`build/appimage-tools`. The full builder instead keeps its AppImage staging and
tools inside `build/linux`. The download flag fetches only the five build tools
listed in [appimage-tools.json](appimage-tools.json), with fixed sizes and SHA-256.
Prepopulate the corresponding tool directory to build without that flag. A
changed or missing pinned asset fails closed. The patchelf archive is verified
before its one named executable is read and checked; other members are not extracted.
The runtime's `continuous` download URL can change upstream; a future mismatch
requires deliberate review and repinning, never a hash bypass.

Default outputs alongside tar.gz:

```text
build/linux/artifacts/VRCT-TTS-<version>-linux-x64-vulkan-release.AppImage
build/linux/artifacts/VRCT-TTS-<version>-linux-x64-vulkan-release.AppImage.sha256
build/linux/artifacts/VRCT-TTS-<version>-linux-x64-vulkan-release.AppImage.manifest.json
```

The builder checks the fixed runtime prefix, allowing only appimagetool's 16-byte
MD5 metadata field, before executing extraction. The extracted tree must pass
distribution policy and match the pre-packaging file/hash/mode/link inventory.
This is an integrity check of a locally built candidate, not a signature or a
sandbox for arbitrary downloaded executables.

## Run

```sh
cd build/linux/artifacts
sha256sum -c ./*.AppImage.sha256
chmod +x VRCT-TTS-<version>-linux-x64-vulkan-release.AppImage
./VRCT-TTS-<version>-linux-x64-vulkan-release.AppImage
```

FUSE must be available to the desktop user. For machines without FUSE:

```sh
APPIMAGE_EXTRACT_AND_RUN=1 ./VRCT-TTS-<version>-linux-x64-vulkan-release.AppImage
```

Extraction needs temporary disk space for the uncompressed payload (about 1.7 GB
for the measured local candidate), in addition to the image. A noexec temporary
filesystem cannot run the extracted program. Both modes preserve settings/data
in the [XDG locations](linux-build-pipeline.md#run-and-inspect); the image is not
the writable model directory. The bundled PipeWire template is under
`usr/lib/vrct-tts/_internal/config/pipewire/`; managed routing still requires
the explicit [host setup](local-setup-linux.md). No host audio service is restarted.

The pinned GTK plugin uses X11, including XWayland on a Wayland desktop. On hosts
with the NVIDIA kernel module loaded, the launcher defaults
`WEBKIT_DISABLE_DMABUF_RENDERER=1` unless the user already set it. This resolves
the locally reproduced GBM allocation failure at the cost of WebKit's faster
rendering path; it is scoped to the GUI and restored before the sidecar starts.
Other GPUs retain their default. An explicit `WEBKIT_DISABLE_DMABUF_RENDERER=0`
requests the original path. This is unrelated to the earlier DPMS-off failure.
See [Tauri's graphics guidance](https://v2.tauri.app/develop/debug/linux-graphics/).

With the NVIDIA fallback active, the main window is also made opaque. The
original transparent window lost its contents during ordinary startup/hover on
this host, despite passing the initial WebDriver screenshot tests. Disabling
transparency alone restored the display in a controlled comparison. Desktop
transparency/transparent rounded corners are therefore unavailable in this mode;
the opacity preference may fade content against the window background instead.
Windows and other rendering paths retain their configured transparency. See the
[reproduction and correction](appimage-rendering-report.md).

## Acceptance and limits

```sh
VRCT_TEST_APPIMAGE=/absolute/path/candidate.AppImage \
VRCT_TEST_APPIMAGE_FUSE=1 VRCT_TEST_NATIVE_GUI=1 VRCT_TEST_NATIVE_ROUTE=1 \
uv run --no-project --python /usr/bin/python3 tools/display_power_guard.py -- \
uv run --no-project --python .venv_linux/bin/python python -m pytest \
  -c tests/voice/pytest.ini tests/platform/test_appimage.py -q
```

Supply `VRCT_TEST_DRIVER` for a different tauri-driver 2.1.0 location. The system
Python running the display guard needs Gio. Tests copy the actual image to a
path with spaces and cover native drawing/shutdown plus private managed routing,
settings persistence and restart muted, for both FUSE and extraction. The
normal-launch test additionally needs ImageMagick and xdotool. It starts the app
without WebDriver, idles for five seconds, then captures the actual X11 window
before and after pointer movement. It checks painted interior coverage and
restores the pointer on completion; no inference control is clicked. The
routing case needs WirePlumber 0.5. It records no physical microphone and uses
no inference models. The CI uses Xvfb and tests extraction; it does not claim
FUSE, physical audio or private routing acceptance on Ubuntu 24.04.

The local build uses CachyOS/glibc 2.44 and includes GLIBC_2.44 references. It is
not an Ubuntu-compatible release. The hosted Ubuntu workflow and other target
machines must be tested separately. Host kernel/glibc, GPU drivers, PipeWire and
command-line audio tools remain requirements. Owned audio helpers currently need
Linux >=6.9. AppImage does not remove these requirements.

OCR weights and Mia2026 are rejected by the package policy. No speech.cpp, RVC or
Seed-VC model is acquired or bundled by this builder. The existing faster-whisper
dependency's two Silero v5 ONNX assets remain explicitly inventoried. RVC/Seed-VC
Python environments and user models stay external. Original licenses are retained;
GTK/WebKit, runtime static dependencies and the complete native/frontend/Rust
license/SBOM review remain publication gates. A build-tool license does not cover
all libraries copied into the image. patchelf is a build tool only and is not
shipped in the runtime tree.

The workflow uploads a candidate only after its build and acceptance steps pass.
It has no release publisher, AUR submission or upstream contact. See
[the local results](appimage-results.json) for measured results and remaining limits.

## Investigation evidence

- [AppImageKit AppRun source](https://github.com/AppImage/AppImageKit/blob/master/src/AppRun.c):
  working directory is `APPDIR/usr`; this matches the GTK plugin's relocated WebKit paths.
- [Pinned GTK plugin](https://github.com/tauri-apps/linuxdeploy-plugin-gtk/blob/dda522bce37387f1b853d9095713bfaa924c8423/linuxdeploy-plugin-gtk.sh):
  generated environment hook and WebKit path rewriting.
- [patchelf relocation fixes](https://github.com/NixOS/patchelf/pull/652): upstream
  fixes support pinning the newer tool; they do not by themselves prove the exact
  cause of the earlier local loader crash. Updating patchelf and correcting the
  launcher are recorded separately from that unproven causal attribution.
- [Tauri AppImage baseline guidance](https://v2.tauri.app/distribute/appimage/):
  build on the oldest intended target; bundling does not guarantee old glibc support.
- Local imozuru records: `tmp/voice-resume/research/appimage/`. During diagnosis,
  one gdb invocation unintentionally ran the user's shell initialization, causing
  mise to fetch starship 1.27.0 and atuin 18.24.2. Subsequent probes disabled gdb's
  startup shell and user configuration. Those user tool installations were not rolled back.
