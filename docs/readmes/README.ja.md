# VRCT-TTS

[English](/docs/readmes/README.en.md)

[VRCT-TTS](https://github.com/kein5/VRCT-TTS)は、[VRCT](https://github.com/misyaguziya/VRCT)を基にkein5が開発する独立したforkです。旧名は`kein5/VRCT.cpp`です。**本家の公式版ではなく、本家開発者やVRChatによる承認・公式サポートを示すものではありません。**

speech.cppによるTTS、外部Seed-VC/RVCによる直接ボイスチェンジ、リアルタイムASR、翻訳発声を追加しています。音声出力とOSC文字出力は独立して組み合わせられます。speech.cppのローカルサーバーはGUIから保存・起動・停止できます。モデルはユーザーが用意します。

## 配布とサポート

独自の配布先は[VRCT-TTS Releases](https://github.com/kein5/VRCT-TTS/releases)、不具合報告・相談先は[VRCT-TTS Issues](https://github.com/kein5/VRCT-TTS/issues)です。本家の配布物にはこのforkの追加機能は含まれません。本家へfork固有の問い合わせを送らないでください。

現在も開発中です。Linuxで自動試験と実モデル試験を進めていますが、完成した配布物の検証、Windows実機試験、聴感、物理的なエンドツーエンド遅延には未確認事項があります。[完了記録](/docs/voice-stack/completion-ledger.md)を参照してください。AURは[配布方式の検討段階](/docs/voice-stack/linux-distribution-proposal.md)で、この作業では登録・公開していません。

本家向け自動公開、Aptabaseテレメトリー、アプリ内更新は無効化しています。ユーザーが選んだ翻訳サービスへの送信まで停止するものではありません。開発時のPython環境は`uv`を使います。現在の開発用sidecarはcheckout内の環境を使うため、そのまま単体のLinuxパッケージにはなりません。

## モデルとライセンス

配布物には制限付き吹き出し検出モデルを含む**すべてのOCR重みを入れません**。必要な重みがないOCR機能は利用できません。開発用ソース内の既存モデルとライセンスは保持するため、checkout全体を配布ZIPにしないでください。

TTS/ASR/VCモデルと参照音声はユーザー管理です。検証用Mia2026は同梱しません。speech.cpp本体の同梱とモデルの同梱は別です。[ライセンス台帳](/docs/voice-stack/licensing.md)と[配布検査](/docs/voice-stack/fork-distribution-isolation.md)を参照してください。依存ライブラリを含む最終監査は公開前の必須条件です。

元の[MIT LICENSE](/LICENSE)、著作権表示、[NOTICE](/NOTICE.md)、OCRモデル固有の利用条件を維持しています。GPL表示のSeed-VC連携を含め、追加要素の条件をアプリ全体のMIT表示で置き換えません。

## 謝辞と上流への還元

原作者のみしゃ（misyaguziya）さん、しいな（Shiina_12siy）さん、レラ（soumt-r）さん、どね（done_vrc）さん、および本家の全コントリビューターに感謝します。

共通の修正はTTS固有機能と分けて提案できる形に整理します。[公開・上流提案方針](/docs/voice-stack/publication-and-upstream.md)に従い、明示的な指示なしに本家へ連絡したり、draftを含むPRを送ったりしません。
