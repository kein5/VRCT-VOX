# VRCT-VOXとは

VRCT-VOXはVRChatでの会話を助けるデスクトップアプリです。翻訳、音声認識（ASR）、テキスト読み上げ（TTS）、ボイスチェンジャー（RVC）、チャット読み取り（OCR）を1つにまとめています。

[VRCT](https://github.com/misyaguziya/VRCT)をもとに、[kein5](https://github.com/kein5)が開発しています。

::: warning VRCTの公式版ではありません
VRCT-VOXはVRCTの開発者やVRChatが承認したものではありません。VRCT-VOXについての質問や不具合の報告は、VRCTの開発者ではなく[VRCT-VOXのIssues](https://github.com/kein5/VRCT-VOX/issues)へお願いします。
:::

## VRCTから増えたこと

### 翻訳を読み上げる

入力した文章や翻訳を[speech.cpp](https://github.com/nyosegawa/speech.cpp)で読み上げ、VRChatのマイクに流します（仮想マイクを使います）。日本語はIrodori、ほかの言語はQwen3-TTSを使います。読み上げと、チャットボックスへの文字の送信は、別々にオンやオフにできます。

詳しくは[テキスト読み上げ（TTS）](../features/tts)へ。

### 自分でも聞く

VRChatに届ける読み上げと同じ音声を、自分のスピーカーやヘッドホンでも鳴らせます。

詳しくは[テキスト読み上げ（TTS）の「自分でも聞く」](../features/tts#自分でも聞く)へ。

### ボイスチェンジャー

RVCまたはSeed-VCの実行環境でマイクの声を変えます。実行環境はライセンスとサイズを確かめて同意すると、設定画面から取得できます。

詳しくは[ボイスチェンジャー（RVC・Seed-VC）](../features/voice-conversion)へ。

### リアルタイム字幕

自分のマイクとほかのプレイヤーの声を、同梱の音声認識サーバーで文字にします。

詳しくは[音声認識（ASR）とリアルタイム字幕](../features/transcription)へ。

### チャット読み取り

VRChatの画面に出たチャットボックスの文字を読み取ります。

詳しくは[チャット読み取り（OCR）](../features/chat-reading)へ。

### モデルの取得

使うモデルはライセンスと容量を確かめて同意してから取得します。

詳しくは[モデルの取得](./models)へ。

### Linux対応

Waylandでのグローバルショートカット、PipeWireの仮想マイク、日本語入力（fcitx/Mozc、ibus）に対応しています。VR UI、ネイティブのWaylandのウィンドウを共有するチャット読み取り、音声タイピングモードの貼り付けも使えます。

仮想マイクについては[Linuxの音声経路](./linux-audio)へ。

## バージョンと確かめた環境

最初の正式版は0.1.0です。バージョンはVRCT（3.x）とは別に0.1.0から数えます。ベータ版は`develop`ブランチから、正式版は`main`ブランチから出します。

Linux版はCachyOS（KDE Plasma、Wayland）で、実際のモデルを使って動作を確かめています。Windows版はWindows 11のPCで、実際のモデルを使って動作を確かめています。

次は[インストール](./install)へ進んでください。何ができるかを先に見たいときは[やりたいことから探す](./tasks)を、声と文字がどう流れるかは[声と文字の流れ](./how-it-works)を見てください。
