<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/logo-ja-on-dark.svg">
    <img src="../brand/logo-ja-on-light.svg" width="800" alt="VRCT-VOX：音声認識、音声合成、声質変換、文字認識、翻訳">
  </picture>
</h1>

[English](/README.md)

VRCT-VOXは音声認識（ASR）、読み上げ（TTS）、ボイスチェンジ（RVC）、チャット読み取り（OCR）、翻訳をまとめたVRChat向けのデスクトップアプリです。[VRCT](https://github.com/misyaguziya/VRCT)をもとに[kein5](https://github.com/kein5)が開発しています。**VRCTの公式版ではなく、VRCTの開発者やVRChatが承認したものでもありません。**

## できること

- **翻訳した発声**: チャット入力や確定した翻訳を[speech.cpp](https://github.com/nyosegawa/speech.cpp)のTTS（日本語はIrodori、ほかの言語はQwen3-TTS）で読み上げ、VRChatが使う仮想マイクに流します。音声とOSCのチャット文字は別々に設定できるので、自分の声はそのままに、翻訳の音声と文字を足すといった使い方ができます。
- **モニター出力**: 同じ読み上げ音声を自分のスピーカーやヘッドホンでも聞けます（任意）。
- **ボイスチェンジ**: 外部のRVCまたはSeed-VCの実行環境でマイクの声を変換します。WindowsとLinuxではライセンスとサイズを確認したうえで、実行環境をアプリから取得できます。NVIDIAのGPUが必要です。
- **リアルタイム字幕**: 同梱のspeech.cppの音声認識サーバーで自分のマイクとほかのプレイヤーの声を文字にします。
- **同梱サーバー**: speech.cppのサーバーを設定画面から保存・起動・停止できます。
- **モデルの取得**: Irodori、Qwen3-TTS、Haas-ja（日本語の音声認識）、RVCの既定モデルを、ライセンスと容量を確認して同意したうえでHugging Faceから取得できます。サイズとSHA-256を検証し、設定への適用は別の操作です。GPUとVRAMに応じて標準・軽量モデルの目安を出しますが、動作を保証するものではありません。
- **Linux対応**: Waylandでのグローバルショートカット（XDG portal）、PipeWireの仮想マイクとマイク選択、AppImageでの日本語入力（fcitx/Mozc、ibus）に対応しています。VR UI、Waylandネイティブのウィンドウを共有するチャット読み取り、音声タイピングモードの貼り付け（X11/XWaylandのウィンドウ）も使えます。

RVCには音声モデルのほかに実行環境、HuBERT、RMVPEが必要です。[モデル取得の仕様](/docs/voice-stack/model-downloads.md)と、Windowsでは[Windowsで音声機能を使う](/docs/voice-stack/local-setup-windows.md)、Linuxでは[Linuxの手順](/docs/voice-stack/local-setup-linux.md)を参照してください。

## 配布状況

現在のバージョンは **[0.1.0-beta.7](https://github.com/kein5/VRCT-VOX/releases/tag/v0.1.0-beta.7)**（プレリリース）です。バージョン番号は本家VRCT（3.x）とは別に0.1.0から数えます。ベータ版は`develop`から、正式版は`main`から公開します。

- **Linux**: AppImageとtar.gz（x64、Vulkan）。CachyOS（KDE Plasma Wayland）で実際のモデルを使って試験しています。
- **Windows**: インストーラーとzip（CPU版）、CUDA版のzip。Windows 11の実機で実際のモデルを使って試験しています（[検証記録](/docs/voice-stack/windows-voice-report.md)）。電子署名がないため、初回起動時にSmartScreenの警告が出ます。

各ファイルの`.sha256`と`SHA256SUMS-*`でダウンロードしたファイルを確認できます（電子署名ではありません）。アプリ内の自動更新は無効です。AURでの配布は予定していますが、まだ登録していません。

このベータ版には次の制限があります。

- チャット読み取り（OCR）にはモデルが必要ですが、同梱していません。利用条件に同意したうえで、設定の「チャット読み取り」で取得してください。LinuxではVRChatのウィンドウをXWayland経由で読み取ります。Waylandネイティブのウィンドウ（gamescopeの中のVRChatなど）は、ウィンドウを共有すると読み取れます。設定の「チャット読み取り」で「ウィンドウを共有…」を押すと、デスクトップのウィンドウ選択画面が開きます。
- LinuxのVR UIと、VRヘッドセットの画面のチャット読み取りは、SteamVRの代わりになる試験用の仕組みでだけ確認しました。実際のヘッドセットでは確認していません。Linux版の動作確認はKDE Plasma（Wayland）だけです。
- Google・Bing・PapagoのWeb翻訳は使えません（ライセンスの項を参照）。

不具合の報告や質問は **[Issues](https://github.com/kein5/VRCT-VOX/issues)** へ、OS・バージョン・再現手順と、個人情報を除いたログを添えてお寄せください。脆弱性は[SECURITY.md](/SECURITY.md)の手順で非公開に報告してください。VRCT-VOXについての問い合わせを本家VRCTの開発者へ送らないでください。

## 使い始めるには

- [TTS設定ガイド](/docs/voice-stack/tts-quickstart-ja.md)
- [トラブルシューティング](/docs/voice-stack/troubleshooting.md)
- [モデル取得とGPU・VRAMの目安](/docs/voice-stack/model-downloads.md)
- [本家VRCTのドキュメント](https://misyaguziya.github.io/VRCT-Docs/)（本家アプリの説明で、VRCT-VOXの音声機能は含みません）

## 名称と保存先

実行ファイルと配布物は`vrct-vox` / `VRCT-VOX`、アプリIDは`io.github.kein5.vrct-vox`です。Linuxでは設定・データ・キャッシュを`vrct-vox`ディレクトリ（`~/.config/vrct-vox`など）に保存します。詳しくは[名称と識別子](/docs/voice-stack/project-rename.md)を参照してください。

## プライバシーとモデル

VRCT-VOXはオフにしない限り、2種類の利用状況の通知をVRCT-VOXの受信サーバーへ送ります（「設定」→「高度な設定」の「利用状況を送信する」）。起動したこと（1日に1回）と、エラーの種類を表す固定のコード（同じコードにつき1日に1回）です。どちらにもアプリのバージョン、OSの種類とバージョン、表示言語、PCの構成（CPU、メモリ、GPUとそのドライバのバージョン）が付きます。送られる内容はアプリの「送信される内容を見る」でそのまま確かめられます。会話の文字や音声、マイクやスピーカーの名前、ユーザー名は送りません。最初に出るお知らせに答えるまでは何も送りません。本家VRCTのAptabaseのテレメトリーは使いません（本家の古いキーファイルが残っていても送信しません）。ユーザーが選んだ翻訳サービスや音声サービスには、送った文字や音声が届きます。利用状況の送信を止めても、すべての機能がオフラインになるわけではありません。

モデルは同梱していません。TTS・音声認識・RVC・Seed-VCのモデルは、ユーザーが求めたときだけ取得するか、ユーザー自身が用意します。配布物にはOCRの重みを一切入れていません。本家のチャット欄検出モデルはforkの配布物に含めることが許されていないためです。リポジトリには、その[利用条件](/src-python/models/ocr/onnx/LICENSE.txt)が認める開発用途のためだけに残しているので、ソース一式をそのまま配布しないでください。検証用の音声Mia2026は配布しません。同梱のspeech.cpp本体にはそれぞれの表記があり、モデルのライセンスはモデルごとに異なります。

## ライセンスと謝辞

VRCT-VOXは[MIT License](/LICENSE)で、本家VRCTの著作権表示を残しています。外部エンジン、モデル、GPL表示のSeed-VC連携にはそれぞれの条件があり、音声機能全体をMITとは主張しません。配布物に含まれるLGPL・GPLの部品、ソースの入手先、差し替え方法は[NOTICE](/NOTICE.md)にあります。GPLのx264/x265を含むPyAVと、公式VRCT専用ライセンスの`translator_engines`は配布しません。`translator_engines`を配布しないため、Google・Bing・PapagoのWeb翻訳は使えません。

本家VRCTの、みしゃ（misyaguziya）さん（メイン開発）、しいな（Shiina_12siy）さん（UI/UXとローカライズ）、レラ（soumt-r）さん（技術的な助言）、どね（done_vrc）さん（ロゴ）、そして[すべての貢献者](https://github.com/misyaguziya/VRCT/graphs/contributors)に感謝します。VRCT-VOXは皆さんの成果の上に成り立っています。現在は本家に追従しておらず、リポジトリの所有者が決めない限り本家へ何かを送ることはありません（[方針](/docs/voice-stack/publication-and-upstream.md)）。

VRChatおよび関連する名称はVRChat Inc.の商標または登録商標です。VRCT-VOXはVRChat Inc.と関係ありません。

## 開発

Pythonの環境には`uv`を使います。`npm run doctor`で開発環境を確認し、検査用の依存を`npm run setup:headless`、UIの依存を`python tools/dev.py setup --scope ui`で入れます。`npm run check`で開発ツール・Nodeのテスト・lintを実行します。音声・バックエンド・Rustの検査、ブラウザでのテスト、Cocogittoは[開発ガイド](/docs/development.md)を、ブランチとPRの決まりは[CONTRIBUTING.md](/CONTRIBUTING.md)を参照してください。

- [ビルドとCIのガイド](/docs/readme_build.md)
- [Linuxのビルドパイプライン](/docs/voice-stack/linux-build-pipeline.md)と[AppImage](/docs/voice-stack/appimage.md)
- [配布候補と下書きの手順](/docs/voice-stack/release-candidates.md)
- [音声機能のライセンスと配布の範囲](/docs/voice-stack/licensing.md)
