# Install

Downloads are on [GitHub Releases](https://github.com/kein5/VRCT-VOX/releases). Betas are published as pre-releases.

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

### Where settings and data are stored

| Content | Location |
|---|---|
| Settings and logs | `~/.config/vrct-vox` (under `$XDG_CONFIG_HOME` if set) |
| Data | `~/.local/share/vrct-vox` |
| Cache | `~/.cache/vrct-vox` |

The AppImage and the tar.gz use the same locations.

## Windows

| Kind | File |
|---|---|
| Installer | `VRCT-VOX_<version>_x64-setup.exe` |
| ZIP (CPU) | `VRCT-VOX.zip` |
| ZIP (CUDA) | `VRCT-VOX_cuda.zip` |

::: warning The Windows build has not been tested on a real PC yet
The Windows build has passed automated builds and package checks only. It has not been tested on a real Windows PC yet. It is not code-signed, so SmartScreen warns on first launch.
:::

## Check your download

Every file has a `.sha256`, and `SHA256SUMS-*` lists them all. These check that a file is intact; they are not signatures.

## Updates

The in-app updater is disabled. Install a new version from GitHub Releases. Your settings and downloaded models stay in the locations above.

Next, see [First setup](./first-setup).
