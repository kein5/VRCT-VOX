# Install

Downloads are on [GitHub Releases](https://github.com/kein5/VRCT-VOX/releases). The stable release is marked "Latest"; betas are published as pre-releases.

## Linux

There is an x64 Vulkan build in two formats: AppImage and tar.gz.

### AppImage

```sh
sha256sum -c VRCT-VOX-<version>-linux-x64-vulkan-release.AppImage.sha256
chmod +x VRCT-VOX-<version>-linux-x64-vulkan-release.AppImage
./VRCT-VOX-<version>-linux-x64-vulkan-release.AppImage
```

Without FUSE, start it with `APPIMAGE_EXTRACT_AND_RUN=1`. This needs extra temporary space for extraction (about 1.7 GB for the tested version).

### tar.gz

```sh
sha256sum -c VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz.sha256
tar -xzf VRCT-VOX-<version>-linux-x64-vulkan-release.tar.gz
./VRCT-VOX/vrct-vox
```

Keep the `VRCT-VOX` folder together. WebKitGTK 4.1, GTK 3, PipeWire, Vulkan and similar libraries come from your system. It is not promised to work on every distribution.

### Where settings and data are stored (Linux)

| Content | Location |
|---|---|
| Settings and logs | `~/.config/vrct-vox` (under `$XDG_CONFIG_HOME` if set) |
| Data | `~/.local/share/vrct-vox` |
| Cache | `~/.cache/vrct-vox` |

The AppImage and the tar.gz use the same locations.

## Windows

| Kind | File | Choose it when |
|---|---|---|
| Installer | `VRCT-VOX_setup.exe` | The usual choice. It asks for the CPU or the GPU version on the way |
| ZIP (CPU) | `VRCT-VOX.zip` | You want to run from an unpacked folder without installing |
| ZIP (CUDA) | `VRCT-VOX_cuda.zip` | The same, with an NVIDIA GPU |

The CPU version runs on any PC. The GPU (CUDA) version is for PCs with an NVIDIA GPU: Whisper speech recognition and local translation can run on the GPU, and the download is larger. Speech and realtime captions (the bundled speech.cpp) can use a GPU in either version.

::: warning SmartScreen warns on first launch
The Windows build is not code-signed. When "Windows protected your PC" appears, press "More info" and then "Run anyway".
:::

### Where settings and data are stored (Windows)

The settings (`config.json`), logs and downloaded models are inside the folder the app is in.

| Installed with | Location |
|---|---|
| Installer | `%LOCALAPPDATA%\VRCT-VOX` (unless you changed the folder) |
| ZIP | The folder you unpacked it to |

## Check your download

Every file has a `.sha256`, and `SHA256SUMS-*` lists them all. These check that a file is intact; they are not signatures.

## Updates

The in-app updater is disabled. Install a new version from GitHub Releases. Your settings and downloaded models stay in the locations above.

The Windows installer unpacks and checks the new version before it replaces the old one. If something fails on the way, it puts the old version back. Your settings, models and logs are kept. With a ZIP, your settings and models are inside the unpacked folder, so unpacking a new ZIP to another folder starts without them. Use the installer if you want them carried over on every update.

## One running copy

If you start VRCT-VOX while it is already running, it brings the running window to the front instead of starting again.

Next, see [First setup](./first-setup).
