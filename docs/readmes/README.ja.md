<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/logo-ja-on-dark.svg">
    <img src="../brand/logo-ja-on-light.svg" width="800" alt="VRCT-VOX：音声認識、音声合成、声質変換、文字認識、翻訳">
  </picture>
</h1>

[English](/README.md) · [한국어](README.ko.md) · [繁體中文](README.zh-Hant.md)

VRCT-VOX は、音声認識（ASR）、読み上げ（TTS）、ボイスチェンジ（RVC）、チャット読み取り（OCR）、翻訳をまとめた VRChat 向けのデスクトップアプリです。[VRCT](https://github.com/misyaguziya/VRCT) をもとに [kein5](https://github.com/kein5) が開発しています。**VRCT の公式版ではなく、VRCT の開発者や VRChat が承認したものでもありません。**

## できること

- **翻訳した発声**: チャット入力や確定した翻訳を [speech.cpp](https://github.com/nyosegawa/speech.cpp) の TTS（日本語は Irodori、ほかの言語は Qwen3-TTS）で読み上げ、VRChat が使う仮想マイクに流します。音声と OSC のチャット文字は別々に設定できるので、自分の声はそのままに、翻訳の音声と文字を足すといった使い方ができます。
- **モニター出力**: 同じ読み上げ音声を、自分のスピーカーやヘッドホンでも聞けます（任意）。
- **ボイスチェンジ**: 外部の RVC または Seed-VC の実行環境で、マイクの声を変換します。Windows と Linux では、ライセンスとサイズを確認したうえで、実行環境をアプリから取得できます。NVIDIA の GPU が必要です。
- **リアルタイム字幕**: 同梱の speech.cpp の音声認識サーバーで、自分のマイクとほかのプレイヤーの声を文字にします。
- **同梱サーバー**: speech.cpp のサーバーを設定画面から保存・起動・停止できます。
- **モデルの取得**: Irodori、Qwen3-TTS、Haas-ja（日本語の音声認識）、RVC の既定モデルを、ライセンスと容量を確認して同意したうえで Hugging Face から取得できます。サイズと SHA-256 を検証し、設定への適用は別の操作です。GPU と VRAM に応じて標準・軽量モデルの目安を出しますが、動作を保証するものではありません。
- **Linux 対応**: Wayland でのグローバルショートカット（XDG portal）、PipeWire の仮想マイクとマイク選択、AppImage での日本語入力（fcitx/Mozc、ibus）に対応しています。VR UI、Wayland ネイティブのウィンドウを共有するチャット読み取り、音声タイピングモードの貼り付け（X11/XWayland のウィンドウ）も使えます。

RVC には、音声モデルのほかに実行環境、HuBERT、RMVPE が必要です。[モデル取得の仕様](/docs/voice-stack/model-downloads.md)と、Windows では [Windows で音声機能を使う](/docs/voice-stack/local-setup-windows.md)、Linux では [Linux の手順](/docs/voice-stack/local-setup-linux.md)を参照してください。

## 配布状況

現在の版は **[0.1.0-beta.5](https://github.com/kein5/VRCT-VOX/releases/tag/v0.1.0-beta.5)**（プレリリース）です。版番号は本家 VRCT（3.x）とは別に 0.1.0 から数えます。ベータ版は `develop` から、正式版は `main` から公開します。

- **Linux**: AppImage と tar.gz（x64、Vulkan）。CachyOS（KDE Plasma Wayland）で実際のモデルを使って試験しています。
- **Windows**: インストーラーと zip（CPU 版）、CUDA 版の zip。Windows 11 の実機で、実際のモデルを使って試験しています（[検証記録](/docs/voice-stack/windows-voice-report.md)）。電子署名がないため、初回起動時に SmartScreen の警告が出ます。

各ファイルの `.sha256` と `SHA256SUMS-*` で、ダウンロードしたファイルを確認できます（電子署名ではありません）。アプリ内の自動更新は無効です。AUR での配布は予定していますが、まだ登録していません。

このベータ版の既知の制限:
- チャット読み取り（OCR）にはモデルが必要ですが、同梱していません。利用条件に同意したうえで、設定の「VRChat」の「チャット読み取り」で取得してください。Linux では、VRChat のウィンドウを XWayland 経由で読み取ります。Wayland ネイティブのウィンドウ（gamescope の中の VRChat など）は、ウィンドウを共有すると読み取れます。設定の「VRChat」の「チャット読み取り」で「ウィンドウを共有…」を押すと、デスクトップのウィンドウ選択画面が開きます。
- Linux の VR UI と、VR ヘッドセットの画面のチャット読み取りは、SteamVR の代わりになる試験用の仕組みでだけ確認しました。実際のヘッドセットでは確認していません。Linux 版の動作確認は KDE Plasma（Wayland）だけです。
- Google・Bing・Papago の Web 翻訳は使えません（ライセンスの項を参照）。

不具合の報告や質問は **[Issues](https://github.com/kein5/VRCT-VOX/issues)** へ、OS・版・再現手順・個人情報を除いたログを添えてお寄せください。脆弱性は [SECURITY.md](/SECURITY.md) の手順で非公開に報告してください。VRCT-VOX についての問い合わせを本家 VRCT の開発者へ送らないでください。

## 使い始めるには

- [TTS 設定ガイド](/docs/voice-stack/tts-quickstart-ja.md)
- [トラブルシューティング](/docs/voice-stack/troubleshooting.md)
- [モデル取得と GPU・VRAM の目安](/docs/voice-stack/model-downloads.md)
- [本家 VRCT のドキュメント](https://misyaguziya.github.io/VRCT-Docs/)（本家アプリの説明で、VRCT-VOX の音声機能は含みません）

## 名称と保存先

実行ファイルと配布物は `vrct-vox` / `VRCT-VOX`、アプリ ID は `io.github.kein5.vrct-vox` です。Linux では設定・データ・キャッシュを `vrct-vox` ディレクトリ（`~/.config/vrct-vox` など）に保存します。詳しくは[名称と識別子](/docs/voice-stack/project-rename.md)を参照してください。

## プライバシーとモデル

Aptabase のテレメトリーは無効です（本家の古いキーファイルが残っていても送信しません）。ただし、ユーザーが選んだ翻訳サービスや音声サービスには、送った文字や音声が届きます。テレメトリーを止めても、すべての機能がオフラインになるわけではありません。

モデルは同梱していません。TTS・音声認識・RVC・Seed-VC のモデルは、ユーザーが求めたときだけ取得するか、ユーザー自身が用意します。配布物には OCR の重みを一切入れていません。本家のチャット欄検出モデルは fork の配布物に含めることが許されていないためです。リポジトリには、その[利用条件](/src-python/models/ocr/onnx/LICENSE.txt)が認める開発用途のためだけに残しているので、ソース一式をそのまま配布しないでください。検証用の音声 Mia2026 は配布しません。同梱の speech.cpp 本体にはそれぞれの表記があり、モデルのライセンスはモデルごとに異なります。

## ライセンスと謝辞

VRCT-VOX は [MIT License](/LICENSE) で、本家 VRCT の著作権表示を残しています。外部エンジン、モデル、GPL 表示の Seed-VC 連携にはそれぞれの条件があり、音声機能全体を MIT とは主張しません。配布物に含まれる LGPL・GPL の部品、ソースの入手先、差し替え方法は [NOTICE](/NOTICE.md) にあります。GPL の x264/x265 を含む PyAV と、公式 VRCT 専用ライセンスの `translator_engines` は配布しません。そのため Google・Bing・Papago の Web 翻訳は使えません。

本家 VRCT の、みしゃ（misyaguziya）さん（メイン開発）、しいな（Shiina_12siy）さん（UI/UX とローカライズ）、レラ（soumt-r）さん（技術的な助言）、どね（done_vrc）さん（ロゴ）、そして[すべての貢献者](https://github.com/misyaguziya/VRCT/graphs/contributors)に感謝します。VRCT-VOX は皆さんの成果の上に成り立っています。現在は本家に追従しておらず、リポジトリの所有者が決めない限り本家へ何かを送ることはありません（[方針](/docs/voice-stack/publication-and-upstream.md)）。

VRChat および関連する名称は VRChat Inc. の商標または登録商標です。VRCT-VOX は VRChat Inc. と関係ありません。

## 開発

Python の環境には `uv` を使います。`npm run doctor` で開発環境を確認し、検査用の依存を `npm run setup:headless`、UI の依存を `python tools/dev.py setup --scope ui` で入れます。`npm run check` で開発ツール・Node のテスト・lint を実行します。音声・バックエンド・Rust の検査、ブラウザでのテスト、Cocogitto は[開発ガイド](/docs/development.md)を、ブランチと PR の決まりは [CONTRIBUTING.md](/CONTRIBUTING.md) を参照してください。

- [ビルドと CI のガイド](/docs/readme_build.md)
- [Linux のビルドパイプライン](/docs/voice-stack/linux-build-pipeline.md)と [AppImage](/docs/voice-stack/appimage.md)
- [配布候補と下書きの手順](/docs/voice-stack/release-candidates.md)
- [音声機能のライセンスと配布の範囲](/docs/voice-stack/licensing.md)
