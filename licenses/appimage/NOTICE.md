# AppImage packaging components

These notices cover selected packaging/runtime components, not the complete
GUI/native library license audit. Original VRCT, speech.cpp and Python notices
remain in the frozen payload. Added GTK/WebKit/GLib and their dependencies need
the project's final native-library inventory and redistribution audit before publication.

- Type2 runtime: AppImage/type2-runtime, commit
  `fedfad51acc2860b2916a1eef32ba4a500ff31ef`, MIT source license reproduced here.
  https://github.com/AppImage/type2-runtime/tree/fedfad51acc2860b2916a1eef32ba4a500ff31ef
  Its statically linked dependencies retain their own conditions; the top-level
  MIT file does not relicense them.
- linuxdeploy: `1-alpha-20251107-1`, MIT license reproduced here.
  https://github.com/linuxdeploy/linuxdeploy/tree/1-alpha-20251107-1
- GTK plugin: tauri-apps/linuxdeploy-plugin-gtk commit
  `dda522bce37387f1b853d9095713bfaa924c8423`, MIT license reproduced here.
  https://github.com/tauri-apps/linuxdeploy-plugin-gtk/tree/dda522bce37387f1b853d9095713bfaa924c8423
- AppImageKit: top-level MIT license and its file/subdirectory exceptions
  reproduced here. https://github.com/AppImage/AppImageKit
- appimagetool 1.9.1 is a build tool, not shipped as a tool in this candidate.
  https://github.com/AppImage/appimagetool/tree/1.9.1

Exact downloaded build-tool hashes, asset IDs and URLs are recorded in
`docs/voice-stack/appimage-tools.json` and the external AppImage manifest.
The project supplies its own AppRun/sidecar scripts. No update information,
signing credential or automatic publisher is embedded by this build.
