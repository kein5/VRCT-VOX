# AppImage candidate design

Extend the existing uv/Linux pipeline with an x86_64 Type 2 AppImage; no release,
upstream contact, registry submission or new voice-model acquisition. Preserve the
tar.gz output and development sidecar. Use the current release candidate as input.

Compared approaches: Tauri's direct bundler is conventional but scans/patches the
whole AppDir, placing Python resources away from its executable and potentially
changing the pinned speech.cpp hash. Wrapping the tar without GUI dependencies
would leave WebKit/GTK installation to users. Select **two-stage linuxdeploy**:
bundle GUI/WebKit/GTK first, then add the byte-identical frozen backend privately.

Layout: GUI `usr/bin/vrct-vox`, sidecar launcher `usr/bin/vrct-vox-sidecar`, frozen
sidecar and `_internal` under `usr/lib/vrct-vox`. AppRun saves the host library path
before GUI hooks; the sidecar launcher restores it before entering PyInstaller.
No GUI library overrides may leak to external VC/PipeWire/speech processes.
The wrapper forwards arguments and handles spaces/relocation. XDG state stays external.

Pin linuxdeploy, GTK plugin, patchelf, appimagetool and Type2 runtime by hash/size/source.
Tool acquisition is explicit, build-time only. Add runtime license text/source
references; retain original notices. Native dependencies need the existing final
license/SBOM/security clearance; this candidate is not publication approval.

Inspect both AppDir and extracted final SquashFS for forbidden assets and outside
links. AppDir may contain internal directory aliases (lib64), but no external or
broken links. Keep the tar/default distribution policies unchanged. Before using
the AppImage's extraction entry, compare its runtime with the pinned one, allowing
only appimagetool's non-code MD5 metadata section. Never execute an unknown runtime.

Validate launch from a path containing spaces, the real GUI, backend persistence
and managed mute/restart. Test normal FUSE launch when available and the explicit
extract-and-run fallback. Record test environment and actual ELF requirements;
do not infer Ubuntu compatibility from a CachyOS build. CI uses Ubuntu24.04 and
Xvfb/extract-and-run; hosted runs remain unverified until observed.

Validated launcher details: use `APPDIR/usr` as cwd for relocated WebKit helper
paths, delegate the generated GTK hook exactly once, and enable the verified
DMA-BUF fallback only when the NVIDIA module is present and the user has not
chosen a value. Restore that override as well as the GUI library environment
before entering the frozen sidecar. The AppImage runtime waiting for extraction
cleanup is not the owned GUI process in the WebDriver acceptance tests.
