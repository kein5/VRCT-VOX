# VRCT-VOX とは

VRCT-VOX は、VRChat での会話を助けるデスクトップアプリです。翻訳、音声認識、読み上げ（TTS）、声の変換（RVC）、チャット読み取り（OCR）を 1 つにまとめています。

[VRCT](https://github.com/misyaguziya/VRCT) をもとに、[kein5](https://github.com/kein5) が開発しています。

::: warning VRCT の公式版ではありません
VRCT-VOX は VRCT の開発者や VRChat が承認したものではありません。VRCT-VOX についての質問や不具合の報告は、VRCT の開発者ではなく [VRCT-VOX の Issues](https://github.com/kein5/VRCT-VOX/issues) へお願いします。
:::

## VRCT から増えたこと

- **翻訳を読み上げる**：入力した文章や翻訳を [speech.cpp](https://github.com/nyosegawa/speech.cpp) で読み上げ、VRChat が使う仮想マイクへ流します。日本語は Irodori、ほかの言語は Qwen3-TTS を使います。声と、チャットボックスへの文字の送信は別々に設定できます。
- **自分でも聞く**：同じ音声を、自分のスピーカーやヘッドホンでも鳴らせます。
- **声の変換**：別に用意した RVC または Seed-VC の実行環境で、マイクの声を変換します。
- **リアルタイム字幕（Linux）**：自分のマイクとほかのプレイヤーの声を、同梱の音声認識サーバーで文字にします。
- **チャット読み取り**：VRChat の画面に出たチャットボックスの文字を読み取ります。
- **モデルの取得**：使うモデルは、ライセンスと容量を確かめて同意してから取得します。
- **Linux 対応**：Wayland でのグローバルショートカット、PipeWire の仮想マイク、日本語入力（fcitx/Mozc、ibus）に対応しています。

## いまの状態

VRCT-VOX はベータ版です。版は VRCT（3.x）とは別に 0.1.0 から数えます。ベータ版は `develop` ブランチから、正式版は `main` ブランチから出します。

- **Linux**：CachyOS（KDE Plasma、Wayland）で、実際のモデルを使って動作を確かめています。
- **Windows**：自動ビルドと配布物の検査だけで、実際の Windows の PC ではまだ試していません。

次は [インストール](./install) へ進んでください。
