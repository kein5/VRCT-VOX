# VRCT-VOX

[English](/docs/readmes/README.en.md)

[VRCT-VOX](https://github.com/kein5/VRCT-VOX)は、[VRCT](https://github.com/misyaguziya/VRCT)を基にkein5が開発する独立したforkです。本家の公式版ではなく、本家開発者やVRChatによる承認・公式サポートを示すものではありません。

speech.cppによるTTS、外部Seed-VC/RVCによる直接ボイスチェンジ、リアルタイムASR、翻訳発声を追加しています。音声出力とOSC文字出力は独立して組み合わせられます。speech.cppのローカルサーバーはGUIから保存・起動・停止できます。設定画面からIrodori、Qwen3-TTS、Haas-ja（日本語ASR）、RVCの既定モデルを取得することもできます。

## 配布とサポート

独自の配布先は[VRCT-VOX Releases](https://github.com/kein5/VRCT-VOX/releases)、不具合報告・相談先は[VRCT-VOX Issues](https://github.com/kein5/VRCT-VOX/issues)です。本家の配布物にはこのforkの追加機能は含まれません。本家へfork固有の問い合わせを送らないでください。

現在も開発中です。Linuxでは実際のAppImageとモデルを使って試験しています。Windows実機、聴感、物理的なエンドツーエンド遅延には未確認事項が残ります。試験した環境と範囲は、[モデル取得・GPU案内の試験記録](/docs/voice-stack/model-downloads-integration-report.md)、[TTS遅延の計測記録](/docs/voice-stack/tts-low-latency-report.md)、[RVCの試験記録](/docs/voice-stack/rvc-index-search-report.md)を参照してください。AURは[配布方式の検討段階](/docs/voice-stack/linux-distribution-proposal.md)で、この作業では登録・公開していません。

本家向け自動公開、Aptabaseテレメトリー、アプリ内更新は無効化しています。ユーザーが選んだ翻訳サービスへの送信まで停止するものではありません。Python環境は`uv`を使います。[Linuxビルドパイプライン](/docs/voice-stack/linux-build-pipeline.md)は開発用sidecarと別にバックエンドを凍結し、speech.cppを含むtar.gz候補を作ります。検証範囲と公開前の残条件は同ガイドを参照してください。

## 使い始めるには

日本語の読み上げは[TTS設定ガイド](/docs/voice-stack/tts-quickstart-ja.md)に沿って設定します。モデルを持っていない場合は、設定画面で提供元・容量・利用条件・保存先を確認し、同意してからダウンロードします。サイズとSHA-256の検証が終わった後、別の操作で設定へ適用します。取得だけで発声やマイク転送が始まることはありません。

GPUとVRAMに応じて標準・軽量モデルの目安を表示します。メモリの確保や動作を保証するものではありません。RVCには音声モデルのほかに実行環境、HuBERT、RMVPEが必要です。[モデル取得の仕様](/docs/voice-stack/model-downloads.md)を参照してください。

日本語TTSの低遅延モードは選択式で、初期設定はオフです。有効にすると待機中の消費電力が増え、ゲームとGPU処理が競合する場合があります。すべての環境で100ms以内になるとは保証していません。

## 名称と保存先

配布物と実行ファイルは`vrct-vox` / `VRCT-VOX`、アプリIDは`io.github.kein5.vrct-vox`です。Linuxでは設定・データ・キャッシュを`vrct-vox`ディレクトリ（`~/.config/vrct-vox`など）に保存します。詳しくは[名称と識別子](/docs/voice-stack/project-rename.md)を参照してください。

開発手順は[ビルドとCIのガイド](/docs/readme_build.md)を参照してください。

## モデルとライセンス

配布物には制限付き吹き出し検出モデルを含むすべてのOCR重みを入れません。必要な重みがないOCR機能は利用できません。開発用ソース内の既存モデルとライセンスは保持するため、checkout全体を配布ZIPにしないでください。

speech.cpp/RVC/Seed-VCのモデルと参照音声はユーザー管理です。検証用Mia2026は同梱しません。既存faster-whisper依存に付属するSilero VAD資源は別途一覧化して監査します。speech.cpp本体の同梱とモデルの同梱は別です。[ライセンス台帳](/docs/voice-stack/licensing.md)と[配布検査](/docs/voice-stack/fork-distribution-isolation.md)を参照してください。依存ライブラリを含む最終監査は公開前の必須条件です。

元の[MIT LICENSE](/LICENSE)、著作権表示、[NOTICE](/NOTICE.md)、OCRモデル固有の利用条件を維持しています。GPL表示のSeed-VC連携を含め、追加要素の条件をアプリ全体のMIT表示で置き換えません。

## 謝辞と上流への還元

原作者のみしゃ（misyaguziya）さん、しいな（Shiina_12siy）さん、レラ（soumt-r）さん、どね（done_vrc）さん、および本家の全コントリビューターに感謝します。

共通の修正はTTS固有機能と分けて提案できる形に整理します。[公開・上流提案方針](/docs/voice-stack/publication-and-upstream.md)に従い、明示的な指示なしに本家へ連絡したり、draftを含むPRを送ったりしません。

## 開発と配布

`npm run doctor`で開発環境を確認します。検査用の依存は`npm run setup:headless`、UIの依存は`python tools/dev.py setup --scope ui`で導入できます。`npm run check`で開発ツール・Nodeテスト・Ruffを実行します。音声・バックエンド・Rustの検査とCocogittoの使い方は[開発ガイド](../development.md)を参照してください。

配布候補は[検証と下書き作成の手順](../voice-stack/release-candidates.md)に従って作成します。公開前に成果物と実機試験の結果を確認してください。

- [改名・UI・開発環境の統合記録](../voice-stack/vox-integration-report.md)
