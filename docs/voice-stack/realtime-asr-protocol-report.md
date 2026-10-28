# Realtime ASRイベント・通信の検証（2026-10-28）

speech.cpp向けの字幕イベント処理とasyncio WebSocket producerを実装した。P3全体の完成ではない。

- `realtime_events.py`: mic/speaker/session/itemで識別し、暫定文を累積、completed全文で置換。失敗・model_limit・clear・終了後の結果を破棄。既知itemのfinalは1回。
- `speechcpp_realtime.py`: 設定応答を確認してから24kHz mono s16leだけを送る。rate/channelの単なるラベル変更はしない。通常はserver_vad、明示manual modeは試験用。
- local HTTP設定からWS URLを作り、proxy/redirectを拒否。音声や本文を含むlibrary debug loggingも無効化。
- pending8発話、1発話4000文字、出力queue32、frame最大100ms/受付時最大250ms齢、pending15秒。接続/設定2秒、送信最大1秒（frameは残り期限まで）、close.5秒。
- feed直列、単一event loop/consumerを前提とする。内部PCM queueを作らず、過負荷はsessionを閉じる。OS TCP bufferや将来capture側のqueueまで制限したとは主張しない。
- 自動再接続・旧PCMの再送なし。明示的に新instance/namespaceを作る。close/障害は未配信結果を捨てるため、UI側もnamespaceの字幕を消す必要がある。
- bounded terminal/event記録は通常の重複防止であり、履歴をすべて追い出した後の悪意ある全イベント再生を永続記憶するものではない。

## 検証範囲

reducer15 FAIL→15 PASS。transportとpending snapshot追加18 FAIL→33 PASS。
実speech.cpp0.9.0/既存ReazonSpeechも含め34 PASS / 1 audioop非推奨warning（8.26秒）。
実通信は既存合成WAVを20msずつ供給し、mic/speakerの2sessionを同時実行。双方final1回、namespace別、余分なfinalなし。
Sileroをロードしないserver_vad要求は拒否され、勝手にmanualへ切り替わらない。

[数値結果](realtime-asr-protocol-results.json)のcommit→finalは、手動commit後の待ち時間のみ。物理発話終端→字幕やVAD遅延ではない。
34ケースにはmock fault/clear/重複/大応答/低速consumer/接続中cancel/異format/旧frame/redirect試験を含む。
音声入力fixtureの24kHz化は既存Python3.11 audioopを試験内だけで使用。製品resamplerやPython3.13対応を完成扱いにしない。
rawは`tmp/voice-resume/realtime-adapter-live/`。音声・書き起こし本文は共有結果に含めない。

## 原典と残件

[固定speech.cpp0.9.0 Realtime仕様](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/docs/server.md#realtime-transcription)、
[websockets15.0.1 asyncio client](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html)、導入済み同版sourceを照合。
`process_redirect`の狭いoverrideを使うため、依存upgrade時にも外部転送拒否テストを必要とする。

Silero取得同意待ち。server_vad実測、capture/正しいresample、UI設定・字幕、既存翻訳/OSC/TTSのfinal接続、実デバイス/Windowsは未完了。
既存SENT/CHAT/RECEIVEDとlegacy providerは変更していない。P2聴感確認も引き続き別ゲート。

回帰: 音声+既存provider/transcriber504 PASS / 10 opt-in SKIP / 7 warnings（16.65秒）。
既定1173 PASS / 16既知FAIL / 6 SKIP / 46 warnings（14.39秒）、失敗名集合は変更なし。
[既知失敗一覧](seed-vc-runtime-report.md#unchanged-default-suite-failures)。
実manual試験で利用者へ渡ったpartialは両sessionとも0件。partial置換はmockで検証しており、実server_vadで暫定字幕が流れることはまだ証明していない。
未知itemのdeltaを捨てる方針を採っているため、manual modeのcommit前の未知item deltaには依存しない。
