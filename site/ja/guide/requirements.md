# 動作環境と推奨スペック

必要なPCの性能は使う機能によって大きく変わります。文字の翻訳と相手の声の字幕だけなら、GPUは必要ありません。読み上げ、ボイスチェンジャー、VRChatを同じPCで同時に使うなら、メモリとGPUに余裕が必要です。

このページの値は試験用のPC 1台で測った値と、モデルの大きさから出した目安です。動作を保証するものではありません。測ったPCの構成はページの最後にあります。

## 対応するOS

| OS | 条件 |
|---|---|
| Windows | 64ビットのWindows 11で確かめています。Windows 10では確かめていません。WebView2 Runtimeが必要です。入っていなければ、インストーラーが取得します。 |
| Linux | x86-64のPCで、glibc 2.39以降、GTK 3、WebKitGTK 4.1が必要です。debとrpmは、Ubuntu 24.04、Debian 13、Fedora 44に入れられることを確かめています。実際のモデルを使った動作は、CachyOS（KDE Plasma、Wayland）で確かめています。 |

macOS版はありません。

Linuxでアプリが管理する音声経路を使うには、Linux 6.9以降、PipeWire、WirePlumber 0.5が必要です（[Linuxの音声経路](linux-audio)）。デスクトップの字幕オーバーレイはX11かXWaylandで動きます。

## メモリ

| 使い方 | アプリが使ったメモリ（測った値） | PCのメモリの目安 |
|---|---|---|
| 翻訳と相手の声の字幕（音声認識はWhisper tiny、どちらもCPU） | 約3.6 GB | 16 GB以上 |
| 読み上げ、字幕、ボイスチェンジャー（RVC）、翻訳、VRの字幕を同時に | 約11.5〜13.1 GB | 32 GB以上 |

「アプリが使ったメモリ」は、VRCT-VOXのプロセスのプライベートメモリの合計を、30分〜2時間の運転で測った値です。「PCのメモリの目安」はこの値にOSとVRChatの分を足して出しました。VRChat自身のメモリは測っていません。

## GPU

| 機能 | 必要なGPU |
|---|---|
| 翻訳、音声認識（Whisper）、チャット読み取り | 必要ありません。CPUで動きます |
| 読み上げ、リアルタイム字幕、話した人を見分ける機能（アプリに入っているspeech.cpp） | Vulkanに対応したGPU。NVIDIA、AMD、Intelのどれでも、内蔵GPUでも動きます。GPUがなければCPUで動きますが、遅くなります |
| ボイスチェンジャー（RVC、Seed-VC） | NVIDIAのGPUと、CUDA 12.8に対応したドライバー |
| Whisperの音声認識とローカルの翻訳をGPUで（WindowsのCUDA版） | NVIDIAのGPU |

読み上げのモデルが使うGPUメモリの目安は次のとおりです。詳しくは[モデルの取得](models#gpuとメモリの目安)にあります。

| モデル | GPUメモリの目安 |
|---|---|
| Irodori-TTS v4.1 Small MF · F16（日本語） | 約2.3 GB |
| Irodori-TTS v4.1 Small MF · Q8_0（日本語、軽量） | 約1.6 GB |
| Qwen3-TTS 0.6B · Q8_0（ほかの言語） | 約1.3 GB |
| Qwen3-TTS 0.6B · Q5_K（ほかの言語、軽量） | 約1.0 GB |

GeForce RTX 3060 Ti（8 GB）で読み上げ、字幕、RVCを同時に動かしたとき、GPU全体の使用量は約4.8 GBでした。VRChat（デスクトップ表示）も同じGPUで動かしたときは約6.1 GBで、いちばん多いときは約7.2 GBでした。すべての機能をVRChatと同じGPUで使うなら、GPUメモリは8 GB以上が目安です。VRのヘッドセットでVRChatを動かしたときの値は測っていません。

## CPU

確かめたCPUはIntel Core i7-1255U（ノートPC向け、10コア12スレッド）だけです。必要な最低限のCPUは決めていません。

| 使い方 | CPU使用率（1論理コアを100%とした値） |
|---|---|
| 翻訳と相手の声の字幕（どちらもCPU） | 21〜34% |
| 読み上げ、字幕、RVCをGPUで動かし、翻訳をCPUで | 63〜137% |

## ストレージの空き容量

| もの | 大きさ |
|---|---|
| アプリ（WindowsのCPU版） | ZIPが約0.4 GB、展開すると約1.1 GB |
| アプリ（WindowsのCUDA版） | ZIPが約1.7 GB、展開すると約3.0 GB |
| アプリ（Linux） | ダウンロードが約0.5 GB、展開すると約1.3 GB |
| 翻訳のモデル（1つ） | 0.4〜3.3 GB |
| 読み上げのモデル（日本語とほかの言語で1つずつ） | 1つ0.8〜1.8 GiB |
| 音声認識のモデル | 0.6〜0.8 GiB |
| RVCの実行環境 | 空きがWindowsで約12 GB、Linuxで約16 GB必要 |
| Seed-VCの実行環境 | 空きがWindowsで約14 GB、Linuxで約18 GB必要 |

すべての機能をそろえるなら、Windowsでは、RVCまでで約20 GB、Seed-VCも使うと約35 GBの空きが目安です。モデルの一覧と大きさは[モデルの取得](models)にあります。

## 測ったPC

| 部品 | 構成 |
|---|---|
| OS | Windows 11 |
| CPU | Intel Core i7-1255U |
| メモリ | 32 GB |
| GPU | NVIDIA GeForce RTX 3060 Ti（8 GB、Thunderbolt接続）、Intel Iris Xe（内蔵） |

測定の記録は開発者向けの[Windowsの音声機能の記録](https://github.com/kein5/VRCT-VOX/blob/develop/docs/voice-stack/windows-voice-report.md)にあります。
