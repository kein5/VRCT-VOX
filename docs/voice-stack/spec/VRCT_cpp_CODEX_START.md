# Codex開始プロンプト — VRCT.cppの低遅延音声統合

あなたはこのリポジトリの実装担当エンジニアです。作業対象は `kein5/VRCT.cpp` のforkであり、現行の `develop` を基準にします。ユーザーが渡した `VRCT_cpp_Codex_Implementation_Spec.md` を **唯一の機能要件の基準** としてすべて読んでください。最初にforkのコミットと既存コードを照合し、必要なら現行実装に合わせてファイル配置を調整してください。

## 実装してください

目標は、VRCTに (1) speech.cppによるTTS、(2) 直接音声チャットを含むリアルタイムVoice Conversion、(3) speech.cppによるリアルタイムASR、(4) 既存VRCT翻訳と再発声、(5) Windows仮想マイク・Linux PipeWireでの音声ルーティングを統合することです。既存の翻訳、OSC、WebSocket、オーバーレイ、UIを壊さないことを最優先にします。

**まずP0とP1を実装・テストして動く縦切りMVPを完成させ、それからP2→P3→P4→P5へ進んでください。** 大量の機能を一度に実装せず、各フェーズでコードレビュー可能なコミットに区切ります。各段階のテスト結果を残し、次へ進むためのゲートを満たしていない場合、偽って完了にしないこと。長い作業でも、調査だけで終わらず、実行可能な機能・テスト・文書を着実に実装してください。

### 実装上の絶対条件

1. `speech.cpp`はTTS/ASR/VADを担当し、**生音声のVoice Conversionは別エンジン**で実装する。外部VCエンジンを実測比較し、未確認APIを捏造しない。まず外部プロセス/仮想音声デバイスadapterを使う。
2. 直接VCの音声経路をSTT/翻訳/TTSの完了待ちにしない。リアルタイム音声callbackでHTTP通信や推論をしない。
3. 既存`MessageDirectionSpec`と`Controller._processMessage`を調べ、最小の非同期フックを追加する。既存の`SENT`/`CHAT`/`RECEIVED`メッセージの形式を壊さない。
4. `speech.cpp`の`POST /v1/audio/speech`はPCMストリームとして扱い、ヘッダ`X-Sample-Rate`に従う。Irodori-TTS-MFが日本語用であること、Qwen3-TTSへの多言語振り分けを尊重する。
5. ASRはspeech.cpp専用REST adapterで接続検証し、その後`/v1/realtime` WebSocketでpartial/finalを扱う。既存OpenAI互換RESTの`temperature=0.0`等の未サポート引数をそのまま流さない。部分字幕をTTSやOSCへ確定発信しない。
6. VRChatに原音とVC/TTSの二重音声を流さず、VC失敗時に生音声を無断で漏らさない。相手の音声・自分のTTSをASRが再取得するフィードバックループを防ぐ。`/input/Voice`のトグル動作を盲目的に制御しない。
7. モデルの実ダウンロードを要求しない自動テストを用意し、API mock/偽VCプロセス/AudioRouterのテストを実装する。実際のVRChat/GPU/仮想マイクが利用できない場合は、実機E2Eを未検証として明記し、手動試験手順を作る。
8. **ライセンス**: フォーク独自の配布物に `src-python/models/ocr/onnx/chatbox_yolox_tiny.onnx` を同梱しない。Seed-VC RealtimeのGPL-3.0、Irodoriの声クローン許諾、Beatriceの条件を確認する。モデル重みは無断同梱しない。
9. 既存VRCTがWindows中心なのでWindows UI統合を先行してよい。ただし利用者のVRChat主環境はCachyOS + WiVRnなので、Linux/PipeWireはP0～P2からCLI/ヘッドレスの実証経路を用意し、ネイティブGUI/配布をP5で仕上げる。Windows用依存関係をLinuxで無理にimportしない。PyInstallerの依存肥大化を避ける。
10. ネット接続のない環境では外部モデルを取得せず、fake実装で可能なコードとテストを完成させる。実測でない遅延数値を達成値として報告しない。

### 最初の実行ステップ

- `git status`、`git rev-parse HEAD`、`package.json`、`src-python/models/message_pipeline.py`、`controller.py`、`transcription_providers.py`、`transcription_transcriber.py`、`websocket_server.py`、UIの設定保存経路、Windowsビルドスクリプトを読む。
- `docs/voice-stack/architecture.md`とADRを用意し、既存のテスト/ビルドを回してP0ベースラインを記録する。
- モックのspeech.cpp TTSサーバーから`PCM`チャンクが届くE2Eテストを作り、次に実サーバーとVRCT UIをつなぐ。テキスト1件送信→音声1件の流れを先に完成させる。
- 後続VCについてはWindowsで候補検証し、Linux対応を先取りして確約しない。実機が利用できない場合、adapter contractとfakeによるテストを先に完成させる。

各フェーズの最後に「コミット／変更ファイル・通過テスト・手元で動くこと・測定値・実機未検証事項・リスク・次フェーズ」を報告してください。未依頼のupstream PR、release、force-pushやライセンス不明なサードパーティ配布は行わないでください。
