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

### 設定とデータの場所（Linux）

| 内容 | 場所 |
|---|---|
| 設定とログ | `~/.config/vrct-vox`（`$XDG_CONFIG_HOME`があればその下） |
| データ | `~/.local/share/vrct-vox` |
| キャッシュ | `~/.cache/vrct-vox` |

AppImageとtar.gzのどちらで起動しても、同じ場所を使います。

## Windows

| 種類 | ファイル | 向いている場合 |
|---|---|---|
| インストーラー | `VRCT-VOX_setup.exe` | ふつうはこれを使います。途中でCPU版かGPU版を選びます |
| ZIP（CPU版） | `VRCT-VOX.zip` | インストールせずに、展開したフォルダーから使いたい場合 |
| ZIP（CUDA版） | `VRCT-VOX_cuda.zip` | 同じくZIPで、NVIDIAのGPUを使う場合 |

CPU版はどのPCでも動きます。GPU版（CUDA版）にはNVIDIAのGPUが必要です。ダウンロードは大きくなりますが、Whisperの音声認識が速くなります。読み上げとリアルタイム字幕（同梱のspeech.cpp）がGPUを使えるのは、どちらの版でも同じです。

::: warning 初めて起動するときにSmartScreenの警告が出ます
Windows版はコード署名をしていません。「WindowsによってPCが保護されました」と出たら、「詳細情報」を押してから「実行」を押します。
:::

### 設定とデータの場所（Windows）

設定（`config.json`）、ログ、取得したモデルは、アプリを入れたフォルダーの中にあります。

| 入れ方 | 場所 |
|---|---|
| インストーラー | `%LOCALAPPDATA%\VRCT-VOX`（インストール先を変えていない場合） |
| ZIP | 展開したフォルダー |

## ダウンロードを確かめる

各ファイルに`.sha256`があり、まとめた`SHA256SUMS-*`もあります。どちらもファイルが壊れていないかを確かめるためのもので、署名ではありません。

## 更新

アプリ内の自動更新は無効にしています。新しいバージョンはGitHub Releasesから入れ直してください。設定とダウンロードしたモデルは上の場所に残ります。

Windowsのインストーラーは新しいバージョンを展開して確かめてから古いバージョンと置き換え、途中で失敗したときは古いバージョンに戻します。設定、モデル、ログは消しません。ZIPの場合、設定とモデルは展開したフォルダーの中にあります。新しいZIPを別のフォルダーへ展開すると引き継がれません。更新のたびに引き継ぎたいときはインストーラーを使ってください。

## 起動は1つだけ

VRCT-VOXが動いている間にもう一度起動すると、もう1つは起動せず、動いているウィンドウを前に出します。

次は[最初の設定](./first-setup)へ進んでください。
