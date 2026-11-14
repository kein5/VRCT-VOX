# インストール

配布物は[GitHub Releases](https://github.com/kein5/VRCT-VOX/releases)にあります。正式版には「Latest」の印が付きます。ベータ版は「Pre-release」として公開しています。対応するOSと、機能ごとに必要なメモリ、GPU、空き容量は[動作環境と推奨スペック](requirements)にあります。

Windowsはこのすぐ下、Linuxは[Linuxの節](#linux)にあります。

## Windows

1. [GitHub Releases](https://github.com/kein5/VRCT-VOX/releases)で「Latest」の印が付いた版の「Assets」から、`VRCT-VOX_setup.exe`をダウンロードします。
2. ダウンロードしたファイルを開きます。SmartScreenの警告が出たときは、下の注意のとおりに進めます。
3. 途中でCPU版かGPU版を選びます。NVIDIAのGPUがあるPCではGPU版（CUDA版）を選べます。
4. インストールが終わったら、VRCT-VOXを起動して[最初の設定](./first-setup)へ進みます。

::: warning 初めて起動するときにSmartScreenの警告が出ます
Windows版はコード署名をしていません。「WindowsによってPCが保護されました」と出たら、「詳細情報」を押してから「実行」を押します。
:::

CPU版はどのPCでも動きます。GPU版（CUDA版）はNVIDIAのGPUがあるPC向けで、Whisperの音声認識とローカルの翻訳をGPUで動かせます。その分ダウンロードが大きくなります。読み上げとリアルタイム字幕（アプリに入っているspeech.cpp）は、どちらの版でもGPUを使えます。

VRChatへ声を届けるには、仮想ケーブルも必要です（[Windowsの音声経路](./windows-audio)）。

### インストールせずに使う（ZIP）

インストールせずに、展開したフォルダーから使いたいときはZIPを使います。

- `VRCT-VOX.zip`（CPU版）
- `VRCT-VOX_cuda.zip`（CUDA版。NVIDIAのGPUを使う場合）

::: details 設定とデータの場所（Windows）
設定（`config.json`）、ログ、取得したモデルは、アプリを入れたフォルダーの中にあります。

| 入れ方 | 場所 |
|---|---|
| インストーラー | `%LOCALAPPDATA%\VRCT-VOX`（インストール先を変えていない場合） |
| ZIP | 展開したフォルダー |
:::

## Linux

x64向けのVulkan版を、deb、rpm、AppImage、tar.gzの4つの形で配布しています（debとrpmは0.3.0から）。ファイルが壊れていないかは、[ダウンロードを確かめる](#ダウンロードを確かめる)の方法で確かめられます。

### deb（Ubuntu、Debian）

```sh
sudo apt install ./VRCT-VOX-<バージョン>-linux-x64-vulkan-release.deb
```

アプリは`/opt/vrct-vox`に入り、アプリの一覧に「VRCT-VOX」が出ます。端末からは`vrct-vox`で起動できます。新しいバージョンも同じコマンドで入れます。消すときは`sudo apt remove vrct-vox`を実行します。

### rpm（Fedora）

```sh
sudo dnf install ./VRCT-VOX-<バージョン>-linux-x64-vulkan-release.rpm
```

入る場所と起動のしかたはdebと同じです。消すときは`sudo dnf remove vrct-vox`を実行します。

debとrpmは、Ubuntu 24.04、Debian 13、Fedora 44で、入れられることと、必要なライブラリがそろうことを確かめています。PipeWireのツールとVulkanのドライバーは推奨のパッケージとして入ります。

### AppImage

```sh
chmod +x VRCT-VOX-<バージョン>-linux-x64-vulkan-release.AppImage
./VRCT-VOX-<バージョン>-linux-x64-vulkan-release.AppImage
```

FUSEを使えない環境では、`APPIMAGE_EXTRACT_AND_RUN=1`を付けて起動します。このときは、展開のための一時的な空き容量が別に必要です（確かめたバージョンでは約1.7 GB）。

### tar.gz

```sh
tar -xzf VRCT-VOX-<バージョン>-linux-x64-vulkan-release.tar.gz
./VRCT-VOX/vrct-vox
```

展開した`VRCT-VOX`フォルダーの中身はばらさずにそのまま置いておいてください。WebKitGTK 4.1、GTK 3、PipeWire、VulkanなどはOSに入っているものを使います。どのディストリビューションでも動くことを約束するものではありません。

::: details 設定とデータの場所（Linux）
| 内容 | 場所 |
|---|---|
| 設定とログ | `~/.config/vrct-vox`（`$XDG_CONFIG_HOME`があればその下） |
| データ | `~/.local/share/vrct-vox` |
| キャッシュ | `~/.cache/vrct-vox` |

deb、rpm、AppImage、tar.gzのどれで起動しても、同じ場所を使います。
:::

## ダウンロードを確かめる

各ファイルに`.sha256`があり、まとめた`SHA256SUMS-*`もあります。どちらもファイルが壊れていないかを確かめるためのもので、署名ではありません。

Linuxでは、ダウンロードしたファイルと同じフォルダーに`SHA256SUMS-linux`も置いて、次を実行します。

```sh
sha256sum -c --ignore-missing SHA256SUMS-linux
```

::: details ビルドの来歴を確かめる（0.3.0から）
各ファイルにはビルドの来歴が付きます。来歴には、このリポジトリのどのワークフローが、どのコミットからそのファイルを作ったかが書かれていて、GitHubが署名しています。来歴はこのリポジトリのワークフローの中でしか作れないので、リリースのファイルを差し替える権限だけでは作れません。

確かめるには[GitHub CLI](https://cli.github.com/)を入れて、ダウンロードしたフォルダーで次を実行します。ファイル名は確かめたいものに替えてください。

```sh
gh attestation verify VRCT-VOX_setup.exe --repo kein5/VRCT-VOX
```

「Verification succeeded!」と出れば、そのファイルはこのリポジトリのワークフローで作られています。失敗した場合は、そのファイルを使わずにIssueで知らせてください。
:::

## 更新

アプリ内の自動更新は無効にしています。新しいバージョンはGitHub Releasesから入れ直してください。設定とダウンロードしたモデルは上の場所に残ります。

Windowsのインストーラーは新しいバージョンを展開して確かめてから古いバージョンと置き換え、途中で失敗したときは古いバージョンに戻します。設定、モデル、ログは消しません。

::: warning ZIPで使っている場合
設定とモデルは展開したフォルダーの中にあります。新しいZIPを別のフォルダーへ展開すると引き継がれません。更新のたびに引き継ぎたいときはインストーラーを使ってください。
:::

## 起動は1つだけ

VRCT-VOXが動いている間にもう一度起動すると、もう1つは起動せず、動いているウィンドウを前に出します。

次は[最初の設定](./first-setup)へ進んでください。
