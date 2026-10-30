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

Silero取得とファイル入力のserver_vad実試験は下記の通り完了。capture/正しいresample、UI設定・字幕、既存翻訳/OSC/TTSのfinal接続、実デバイス/Windowsは未完了。
既存SENT/CHAT/RECEIVEDとlegacy providerは変更していない。P2聴感確認も引き続き別ゲート。

回帰: 音声+既存provider/transcriber504 PASS / 10 opt-in SKIP / 7 warnings（16.65秒）。
既定1173 PASS / 16既知FAIL / 6 SKIP / 46 warnings（14.39秒）、失敗名集合は変更なし。
[既知失敗一覧](seed-vc-runtime-report.md#unchanged-default-suite-failures)。
実manual試験で利用者へ渡ったpartialは両sessionとも0件。partial置換はmockで検証しており、このmanual試験だけでは実server_vadの暫定字幕を証明していなかった（下記追加試験で確認）。
未知itemのdeltaを捨てる方針を採っているため、manual modeのcommit前の未知item deltaには依存しない。


## 承認後のSilero実試験とレビュー修正

ユーザーの同意後、固定Silero v6.2 F32（1,238,624 bytes、MIT）を取得し、
[artifact manifest](speechcpp-vad-artifact.json)のSHA256と一致した。新規録音は行っていない。
実speech.cpp0.9.0へ既存ReazonSpeech（GPU）とSilero（CPU）をロードし、外部通信を切ったnamespace内で試験。
同一の既存合成音声を20msごとにmic・speakerの別セッションへ流した。

- 固定検出設定のoffline VADが2区間を検出し、Realtimeも両セッションで各2 final、各7 partialを受信。finalのitem IDは重複しない。
- 別セッションの1.2秒無音入力とその後250ms待機では字幕更新なし。
- [実測値](realtime-asr-vad-results.json): committed受信→completed受信はmic 18.106/55.578ms、speaker 36.705/106.078ms。
  ファイル送信開始予定→最初のdelta受信は1599.980/1617.792ms。いずれもこの1試行の値で、物理発話終端→字幕のp95ではない。
- 認識文の正確さやVCの聴感品質はこのイベント試験では評価していない。VCはユーザーが現在試聴できず、未確認のまま。

独立レビューはCritical0/Important2/Minor0。両Importantを1回の修正工程で解消した。
旧clear ACKの再送はreducerの重複除外後にしか送信再開を認めない。
手動commitは送信前から15秒の応答期限を持ち、未ACKは1件まで。
新規itemを登録したACKだけで期限を解除し、clear/stopでも破棄する。
Ping/Pongが成功し続けてもcommitの無応答を隠さない。

原典: [固定Events](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/tools/common/realtime-events.cpp#L62)、
[固定clear](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/tools/common/realtime-session.cpp#L453)、
[固定commit](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/tools/common/utterances.cpp#L296)、
[websockets15.0.1 Ping](https://github.com/python-websockets/websockets/blob/15.0.1/src/websockets/protocol.py#L680)。
imozuruの原典5本、検索2バッチ、照合済み引用6件は`tmp/voice-resume/research/realtime-ack-lifecycle/`。

修正後: mock/reducer **36 PASS**、実manual+server_vadを含む **38 PASS / 1 warning（16.42秒）**。
関連voice+legacy ASR **542 PASS / 11 opt-in SKIP / 7 warnings（17.11秒）**。
既定suite **1173 PASS / 16既知FAIL / 6 SKIP / 46 warnings（14.44秒）**、失敗名集合は以前と一致。
Ruff/diff確認成功。rawは`tmp/voice-resume/realtime-reviewed-live/`。

レビューが判断対象外としたcapture/UI/translation/OSC/TTS/deviceは後続工程で受入試験する。
有限履歴をすべて追い出した後の再送を永続排除する機能は追加しない。利用者の明示再接続は新namespaceとする。
上流連絡・PR・公開操作は実施していない。
