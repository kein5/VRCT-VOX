# インストール

配布物は [GitHub Releases](https://github.com/kein5/VRCT-VOX/releases) にあります。ベータ版は「Pre-release」として公開しています。

## Linux

x64 向けの Vulkan 版を、AppImage と tar.gz の 2 つの形で配布しています。

### AppImage

```sh
sha256sum -c VRCT-VOX-<版>-linux-x64-vulkan-release.AppImage.sha256
chmod +x VRCT-VOX-<版>-linux-x64-vulkan-release.AppImage
./VRCT-VOX-<版>-linux-x64-vulkan-release.AppImage
```

FUSE を使えない環境では、`APPIMAGE_EXTRACT_AND_RUN=1` を付けて起動します。このときは、展開のために一時領域が別に必要です（手元の版では約 1.7 GB）。

### tar.gz

```sh
sha256sum -c VRCT-VOX-<版>-linux-x64-vulkan-release.tar.gz.sha256
tar -xzf VRCT-VOX-<版>-linux-x64-vulkan-release.tar.gz
./VRCT-VOX/vrct-vox
```

`VRCT-VOX` フォルダーはまとめて置いたままにしてください。WebKitGTK 4.1、GTK 3、PipeWire、Vulkan などはシステムのものを使います。どのディストリビューションでも動くことを約束するものではありません。

### 設定とデータの場所

| 内容 | 場所 |
|---|---|
| 設定とログ | `~/.config/vrct-vox`（`$XDG_CONFIG_HOME` があればその下） |
| データ | `~/.local/share/vrct-vox` |
| キャッシュ | `~/.cache/vrct-vox` |

AppImage と tar.gz のどちらで起動しても、同じ場所を使います。

## Windows

- インストーラー：`VRCT-VOX_<版>_x64-setup.exe`
- ZIP（CPU 版）：`VRCT-VOX.zip`
- ZIP（CUDA 版）：`VRCT-VOX_cuda.zip`

::: warning Windows 版はまだ実機で試していません
Windows 版は自動ビルドと配布物の検査を通ったものです。実際の Windows の PC での動作はまだ確かめていません。また、コード署名をしていないため、初めて起動するときに SmartScreen の警告が出ます。
:::

## ダウンロードを確かめる

各ファイルに `.sha256` があり、まとめた `SHA256SUMS-*` もあります。これはファイルが壊れていないかを確かめるためのもので、署名ではありません。

## 更新

アプリ内の自動更新は無効にしています。新しい版は、GitHub Releases から入れ直してください。設定とダウンロードしたモデルは、上の場所に残ります。

次は [最初の設定](./first-setup) へ進んでください。
