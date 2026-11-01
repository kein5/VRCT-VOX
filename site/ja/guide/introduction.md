# VRCT-VOXとは

VRCT-VOXは、VRChatでの会話を助けるデスクトップアプリです。翻訳、音声認識、読み上げ（TTS）、声の変換（RVC）、チャット読み取り（OCR）を1つにまとめています。

[VRCT](https://github.com/misyaguziya/VRCT)をもとに、[kein5](https://github.com/kein5)が開発しています。

::: warning VRCTの公式版ではありません
VRCT-VOXはVRCTの開発者やVRChatが承認したものではありません。VRCT-VOXについての質問や不具合の報告は、VRCTの開発者ではなく[VRCT-VOXのIssues](https://github.com/kein5/VRCT-VOX/issues)へお願いします。
:::

## VRCTから増えたこと

| 機能 | 内容 |
|---|---|
| 翻訳を読み上げる | 入力した文章や翻訳を[speech.cpp](https://github.com/nyosegawa/speech.cpp)で読み上げ、VRChatが使う仮想マイクへ流します。日本語はIrodori、ほかの言語はQwen3-TTSを使います。声と、チャットボックスへの文字の送信は別々に設定できます。 |
| 自分でも聞く | 同じ音声を、自分のスピーカーやヘッドホンでも鳴らせます。 |
| 声の変換 | 別に用意したRVCまたはSeed-VCの実行環境で、マイクの声を変換します。 |
| リアルタイム字幕（Linux） | 自分のマイクとほかのプレイヤーの声を、同梱の音声認識サーバーで文字にします。 |
| チャット読み取り | VRChatの画面に出たチャットボックスの文字を読み取ります。 |
| モデルの取得 | 使うモデルは、ライセンスと容量を確かめて同意してから取得します。 |
| Linux対応 | Waylandでのグローバルショートカット、PipeWireの仮想マイク、日本語入力（fcitx/Mozc、ibus）に対応しています。 |

## いまの状態

VRCT-VOXはベータ版です。版はVRCT（3.x）とは別に0.1.0から数えます。ベータ版は`develop`ブランチから、正式版は`main`ブランチから出します。

Linux版は、CachyOS（KDE Plasma、Wayland）で、実際のモデルを使って動作を確かめています。Windows版は自動ビルドと配布物の検査だけで、実際のWindowsのPCではまだ試していません。

次は[インストール](./install)へ進んでください。
