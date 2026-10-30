# Realtime字幕・確定翻訳の製品接続（2026-10-28）

Linuxの専用Realtime設定、mic/speaker独立の開始・停止、字幕の同一行更新、確定翻訳、大きいオーバーレイのpending/history管理を実装した。
実Tauri/全Modelから、私有PipeWire・承認済みspeech.cpp/ReazonSpeech/Sileroへ接続する受入試験が通過した。
**翻訳は本番LMStudio adapterに固定応答を返すHTTP試験サーバーである。実翻訳モデルの品質・速度の検証ではない。**

## 実装と境界

- source別RealtimeSessionが取得・変換・WSを所有。update queue32、final queue4、確定処理の期限はWS受信から2秒。取得時刻からのE2E期限とは区別する。
- partial/final/translatedをsource・namespace・generation・item ID・revisionで同じUI行へ反映。旧世代、逆順、停止済みpendingの復活を拒否する。
- stopは世代を先に無効化し、capture停止を通知する。翻訳・描画の完了を受信スレッドで待たない。非協調な処理が残ると再開を拒否し、workerを増殖させない。
- 同じsourceのlegacy transcript/energy取得と排他。speakerのRealtime結果はlegacy再送設定がONでもOSC/TTSへ送らない。Realtime micもこの段階ではTTSへ送らない。
- 設定は保存するが、再起動・再接続では自動録音しない。端点は明示identity。同名で再作成された別端点へ自動接続しない。
- Realtime大きいオーバーレイはpending置換、final履歴への一回追加、翻訳による同じ履歴更新を実装。小さいオーバーレイは従来providerのまま。HMDでの表示は未検証。
- 字幕イベントはUIへ配送するが、常時process.logへ本文を保存しない。既存の明示的な確定本文logger設定は維持する。
- 接続済み外部翻訳を選択し、CTranslate2が利用不可の場合はローカル重みを必須ロードしない。CTranslate2利用可能時は従来のwarm fallbackを維持する。外部翻訳とローカルfallbackの両方が使えなければ既存の失敗処理となる。

## 実アプリ試験

`tests/platform/test_native_realtime.py`、[結果JSON](realtime-captions-results.json)。レビュー修正後の実試験1件、25.15秒でPASS。
Tauri/WebKitGTK・実Python sidecar・全Controller/Model・実ASR/VAD・私有OS音声取得を使用した。HTTP翻訳peerだけが固定応答である。
既存4.88秒の合成fixtureを使い、新規録音・モデル取得は行っていない。外部ネットワークはnamespaceで遮断し、UDPも私有loopbackへ送った。VRChat/HMDは試験経路に含まない。

| 確認項目 | 観測 |
|---|---|
| mic/speaker同時取得 | 既存fixture各2発話、各2確定字幕 |
| 字幕置換と翻訳 | 4つのDOM行を維持して文字数・翻訳表示が更新。別行の増殖なし |
| 確定翻訳 | 本番LMStudio adapterからHTTP要求4件、4行とも訳文表示 |
| OSCの送信元 | 2UDPをそれぞれmicの訳文と照合。speakerの再送なし |
| 停止 | 両capture nodeの終了後に同じfixtureを再送して、字幕・翻訳要求の追加0 |
| 保存・再起動 | 選択を復元し、両source停止・capture nodeなし |
| 常時診断ログ | `/run/realtime_caption`の本文保存なし |
| 実描画・終了 | DPMS guard下でrAF・不透明画像・実アプリ終了を確認 |

DOM観測時刻はブラウザの`performance.now()`であり、発話終端・capture時刻・ASR確定時刻と同期していない。これからE2E遅延を算出しない。
本文・PCM・個人の参照音声は共有結果JSONへ含めていない。

## 回帰と修正履歴

Task1–3でsession/Controller/IPC/表示/overlayのRED→GREENを実施。実ASR/VADと両ブラウザUIを含む音声suiteは564 PASS/7 Seed opt-in SKIP。
受入修正後も564 PASS/7 SKIP/2 warnings（56.62秒）。標準suiteは1181 PASS/16既知FAIL/6 SKIP/46 warnings（14.95秒）で、失敗名は変更前と完全一致。
受入試験の最初の失敗から、外部翻訳でもCTranslate2を必須ロードしていた既存処理を修正した（3 RED→GREEN、関連31 PASS）。
送信元と翻訳先が同じだった試験設定を修正し、外部通信遮断の通知は実UIの閉じる操作で除いた。
常時診断ログへの字幕保存も1 RED→GREENで修正し、実アプリで保存されないことを確認した。
raw試験は`tmp/voice-resume/realtime-native-{first,second,third,final,attribution}.log`、各basetemp内。
独立レビューImportant4件を1回のRED→GREENで修正し、音声568 PASS、標準1194 PASS/既知16 FAIL、実アプリ1 PASSを確認した。
[指摘・修正・保留1件・全判断記録](realtime-captions-review.md)。最終rawは`realtime-review-{red,green,voice,default}.log`と`realtime-native-reviewed.log`。

## 未検証・次工程

物理マイクの発話終端から字幕/訳文までのp50/p95、実MTモデル、VRChat/HMD併用、Windows、30分混在GPU負荷は未検証。
native legacy recorderへの切替は、私有PipeWireだけではhost Pulse/ALSAを隔離できないため実行していない。Controller排他テストは通過しているが、実legacy録音の代わりにはしない。
途中の翻訳・描画待ちに対する停止は部品試験で検証。native受入試験は確定後の停止と入力再送であり、発話途中停止の実測とは区別する。
Seed-VCの聴感品質・製品統合、P4 mic訳文発声、両OS配布・ライセンス条件は別工程。全機能完成・公開可能とは判断していない。
