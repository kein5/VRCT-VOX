# UI部品からstdio・音声出力までの統合試験

既存のController単体試験と、VoiceEventBusへ直接投入する実TTS試験の間を検証する。
本番の`MessageInputBox`、`VoiceSettings`、Jotai state、送信hook、応答routeをブラウザで動かし、
JSON/base64を子processのstdinへ渡す。本番Mainのreceiver・mapping・workerとControllerを通して
実HTTP provider・AudioRouter・VoiceRouteへつなぎ、専用PipeWire sourceで録音する。

## 今回選ぶ境界

| 方法 | 判断 |
|---|---|
| Linux版Tauriと全Model runtimeを起動 | 最終的に必要。今回のpreflightはPython依存不足とCargoの未取得依存で停止した。全GUI移植・モデル初期化まで一度に拡張しない |
| 本番UI部品＋本番stdio/Controller＋注入サービス | 今回の検証担当の選択。input・response・queue・cancel・音声の接続を実行できる。Tauri接続と全サービス初期化の合格証拠にはしない |
| 既存のController／VoiceEventBus試験だけ | 既存証拠として維持。UIの設定保存、再開、送信ID、応答処理を通らないため今回の代わりにしない |

`tests/voice/ui-entry/`は試験用の組立画面で、本番アプリの新しい画面やLinux起動モードではない。
Playwrightの[ブラウザからPythonへの関数公開](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-expose-function)で
`backend_subprocess.write`を試験用の子processへ接続し、20ms間隔でstdoutの応答をUIへ渡す。
Tauri shell/plugin IPC、`StartPythonController`、アプリ全体の初期化・配置・操作は対象外。

`entry_fixture.py`は既存Controller試験のimport境界を再利用し、翻訳・overlay・重いModel依存を注入する。
Controllerの初期化前後を合成して成功扱いにはせず、`Controller.init()`を実行しないことを明記する。
configは独立した試験用オブジェクト。設定ファイルの永続化・再起動後の復元は未検証。
`getInputTranslate`は制御可能な確定訳fixtureであり、実翻訳エンジンの性能・品質は測らない。
履歴とWebSocketはControllerからの呼出payloadを記録する。実履歴保存・WebSocket通信のE2Eではない。
OSCは本番OSCHandlerから実localhost UDPへ送信してデコードする。VRChatへは送信しない。

## 判定するシナリオ

- 通常送信は同じIDのUIログへ完了応答が届き、OSC・履歴・WebSocket呼出・TTSは各1件。
- 音声は要求ごとに受け取ったHTTP PCMとsource録音を照合し、1回だけ検出する。
- 取消はその発声と待機queueを失効させる。muteは明示解除まで保持し、新推論を起動しない。
- OFFは音声を出さずにテキストを届け、再度ONにした後の新しい発声は動く。
- 通常worker 3本が埋まっても停止が応答する。停止前に受付済みの文章は後からテキストとして届くが発声しない。
- 不正設定は現在の設定を維持し、backendからのエラーがUIに表示される。
- 原文は翻訳待ちでも発声する。訳文は確定まで待ち、停止中に確定した古い訳は発声しない。新要求は選択slotの訳だけを発声する。
- 推論serverのlistener消失は無音化してUIにエラーを示す。停止中もテキストは届き、再起動だけで過去発話を再送しない。
- 全送信IDとUIログ、OSC packet・履歴・WebSocket呼出件数を照合する。
- inputの二重送信／停止欠落を試験用接続に挿入したnegative controlは失敗しなければならない。

停止のstdio書込直前→source無音の個別条件は250ms。ブラウザclick操作開始からの500msは
自動操作の待機も含む診断条件であり、製品UIの性能目標を置き換えない。発声完了・停止後は2秒以上の連続無音、
音声非出力ケースは待機中の無音を確認する。全caseで録音readerの継続とsource identityの保持を確認する。
モデル単体TTFA・物理的な音到達・p95は別の測定。[今回の結果](ui-entry-report.md)は別記する。

## 再実行

Linux、node_modules、PipeWire/WirePlumber、ビルド済み`build/vrct-voice-gate`、既存Chromiumが必要。
通常のPipeWire設定・既定デバイス・物理マイクは変更しない。browserは新規の非永続contextを使う。
試験依存は製品venvから分離する。新しいTTSモデルやbrowserの自動取得処理は持たない。

```sh
python tools/dev.py setup --scope browser
uv run --no-project --python build/dev/browser-venv/bin/python python tests/voice/ui_entry_acceptance.py \
  --chromium /path/to/existing/chrome --output /tmp/vrct-ui-fixture-new
# 既存speech.cppを使う場合は次の引数を追加
# --model /path/to/existing-Irodori-MF-F16.gguf
# 意図的な故障は別の出力先で実行し、exit 1と該当理由を要求する
# --negative-control duplicate-chat または --negative-control drop-stop
```

`--model`なしはモデル不要のPCM HTTP fixture。実モデル試験との遅延値を混ぜない。
出力には試験用の生成音声、画面、wire応答、source hash、個別case、後片付け結果を保存する。
失敗試行を上書きせず、常に新しい出力directoryを指定する。raw成果物は`tmp/`に留める。
