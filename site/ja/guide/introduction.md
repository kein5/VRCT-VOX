# VRCT-VOXとは

VRCT-VOXはVRChatでの会話を助けるデスクトップアプリです。翻訳、音声認識（ASR）、テキスト読み上げ（TTS）、ボイスチェンジャー（RVC）、チャット読み取り（OCR）を1つにまとめています。

[VRCT](https://github.com/misyaguziya/VRCT)をもとに、[kein5](https://github.com/kein5)が開発しています。

::: warning VRCTの公式版ではありません
VRCT-VOXはVRCTの開発者やVRChatが承認したものではありません。VRCT-VOXについての質問や不具合の報告は、VRCTの開発者ではなく[VRCT-VOXのIssues](https://github.com/kein5/VRCT-VOX/issues)へお願いします。
:::

## VRCTから増えたこと

- [テキスト読み上げ（TTS）](../features/tts) 入力した文や訳文を読み上げて、VRChatのマイクに流します。同じ声を自分のスピーカーでも聞けます。
- [ボイスチェンジャー（RVC）](../features/voice-conversion) マイクの声をRVCかSeed-VCで別の声に変えて、VRChatに届けます。
- [リアルタイム字幕](../features/transcription) 自分の声とほかのプレイヤーの声を、アプリに入っている音声認識サーバーで文字にします。
- [チャット読み取り（OCR）](../features/chat-reading) VRChatの画面に出たチャットボックスの文字を読み取ります。
- [Linux版](./install#linux) Waylandのグローバルショートカット、PipeWireの仮想マイク、日本語入力（fcitx/Mozc、ibus）に対応しています。
{.feature-rows}

使うモデルはアプリに入っていません。ライセンスと容量を確かめて同意してから取得します（[モデルの取得](./models)）。

## バージョンと確かめた環境

最初の正式版は0.1.0です。バージョンはVRCT（3.x）とは別に0.1.0から数えます。ベータ版はGitHub Releasesで「Pre-release」として公開しています。

Linux版はCachyOS（KDE Plasma、Wayland）で、実際のモデルを使って動作を確かめています。Windows版はWindows 11のPCで、実際のモデルを使って動作を確かめています。

次は[インストール](./install)へ進んでください。何ができるかを先に見たいときは[やりたいことから探す](./tasks)を、声と文字がどう流れるかは[声と文字の流れ](./how-it-works)を見てください。
