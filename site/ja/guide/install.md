# インストール

配布物は[GitHub Releases](https://github.com/kein5/VRCT-VOX/releases)にあります。正式版には「Latest」の印が付きます。ベータ版は「Pre-release」として公開しています。

## Linux

x64向けのVulkan版をAppImageとtar.gzの2つの形で配布しています。

### AppImage

```sh
sha256sum -c VRCT-VOX-<バージョン>-linux-x64-vulkan-release.AppImage.sha256
chmod +x VRCT-VOX-<バージョン>-linux-x64-vulkan-release.AppImage
./VRCT-VOX-<バージョン>-linux-x64-vulkan-release.AppImage
```

FUSEを使えない環境では、`APPIMAGE_EXTRACT_AND_RUN=1`を付けて起動します。このときは、展開のために一時領域が別に必要です（手元のバージョンでは約1.7 GB）。

### tar.gz

```sh
sha256sum -c VRCT-VOX-<バージョン>-linux-x64-vulkan-release.tar.gz.sha256
tar -xzf VRCT-VOX-<バージョン>-linux-x64-vulkan-release.tar.gz
./VRCT-VOX/vrct-vox
```

`VRCT-VOX`フォルダーはまとめて置いたままにしてください。WebKitGTK 4.1、GTK 3、PipeWire、Vulkanなどはシステムのものを使います。どのディストリビューションでも動くことを約束するものではありません。

### 設定とデータの場所

| 内容 | 場所 |
|---|---|
| 設定とログ | `~/.config/vrct-vox`（`$XDG_CONFIG_HOME`があればその下） |
| データ | `~/.local/share/vrct-vox` |
| キャッシュ | `~/.cache/vrct-vox` |

AppImageとtar.gzのどちらで起動しても、同じ場所を使います。

## Windows

| 種類 | ファイル |
|---|---|
| インストーラー | `VRCT-VOX_setup.exe` |
| ZIP（CPU版） | `VRCT-VOX.zip` |
| ZIP（CUDA版） | `VRCT-VOX_cuda.zip` |

::: warning 初めて起動するときにSmartScreenの警告が出ます
Windows版はコード署名をしていないため、初めて起動するときにSmartScreenの警告が出ます。
:::

## ダウンロードを確かめる

各ファイルに`.sha256`があり、まとめた`SHA256SUMS-*`もあります。どちらもファイルが壊れていないかを確かめるためのもので、署名ではありません。

## 更新

アプリ内の自動更新は無効にしています。新しいバージョンはGitHub Releasesから入れ直してください。設定とダウンロードしたモデルは上の場所に残ります。

Windowsのインストーラーは新しいバージョンを展開して確かめてから古いバージョンと置き換え、途中で失敗したときは古いバージョンに戻します。設定、モデル、ログは消しません。

## 起動は1つだけ

VRCT-VOXが動いている間にもう一度起動すると、もう1つは起動せず、動いているウィンドウを前に出します。

次は[最初の設定](./first-setup)へ進んでください。
