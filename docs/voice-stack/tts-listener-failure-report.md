# 再生待ち中の推論サーバー終了を検出する

2026-10-27。[前回の実TTS試験](live-tts-vrchat-report.md)で残った故障検出の遅れを修正・再検証する。
対象は、発声中にlocalhostの推論サーバーが終了して接続受付がなくなる場合。
すべての通信切断やモデル停止を同じ時間で検出できるという変更ではない。

後続の[修正後VRChat再試験](tts-fixed-vrchat-report.md)で、ホストの通常発声・取消・mute・故障復旧11ケースを確認した。
故障3回の無音化は79〜84ms。本書の独立グラフ30反復とは別群であり、P1全体の完了とはしない。

## 原因と選択

HTTP generatorはAudioRouterのwriteが終わるまで次のreadへ進まない。
このため、外部serverを終了してもTCPに残ったPCMが再生され、前回は独立経路で約15.8秒、
VRChatを使ったホストでは約5.1秒後に無音になった。これらは異なる条件の試行である。

| 方法 | 判断と理由 |
|---|---|
| 有界queueを介した受信・再生分離 | 今回は不採用。満杯で受信が止まれば切断の検出も止まる。失敗検出を保証せず、音声bufferとthread間契約を増やす |
| 発声要求に属する接続受付の監視 | 今回の最小修正として実装担当が選択。再生待ちとは独立して接続拒否を検出し、当該TTSだけを取り消す |
| server processの所有・PID監視 | 今回は不採用。VRCTが起動していない既存localhost serverも設定できるため、PID探索やprocess管理を新設する必要がある |

アーキテクチャBの全体採用や専用音声daemonへの移行を決める変更ではない。
listenerが残る故障や即時再起動を短時間で必ず検出する必要がある場合は、この判断を見直す。
その際は、server identity/heartbeat、接続ごとの終了通知、process所有契約を比較する。

## 実装の契約

[SpeechCppTTS](../../src-python/models/tts/speechcpp_tts.py)の最初のPCM取得後に、要求ごとの監視threadを開始する。
20ms待ってから、同じ数値localhostアドレス・portへtimeout 100msのTCP connectを行い、すぐに閉じる。
HTTP要求、推論要求、音声データは追加送信しない。最大約50 connect/秒で、失敗・終了時は監視を終える。
初音待ちの前提条件やGUIの待ち処理には加えない。

- 明示的な接続拒否のみで`server_unavailable`としてその要求のCancelTokenを取り消す。
- 取消は既存のHTTP shutdown・出力write中断へ伝わり、PCMをdrainせず出力を閉じる。
- timeout・その他のOSErrorは故障の証拠にせず、元のHTTP/request timeoutに任せる。
- 正常EOF・途中close・取消・例外で監視を停止し、threadをjoinしてからHTTP資源を解放する。
- 全体mute、VC経路、既定デバイス、再送キューは操作しない。復旧後は新しい要求だけを処理する。

接続拒否とその他の接続エラーの区別はPython標準の
[ConnectionRefusedError](https://docs.python.org/3.13/library/exceptions.html#ConnectionRefusedError)と
[socket.create_connection](https://docs.python.org/3.13/library/socket.html#socket.create_connection)に従う。
追加依存・モデル配布・外部コードの取り込みはない。[既存ライセンス台帳](licensing.md)の境界を維持する。

## 検証

[回帰テスト](../../tests/voice/test_tts_listener_failure.py)は実HTTPで4秒分のPCMを送り、
一部しか消費していない状態でlistenerを閉じる。旧実装では取消が届かず、実schedulerも出力を続けた。
修正後は、HTTP generatorを進めなくても取消され、schedulerはdrainしない。
遅い正常consumer、probeのtimeout/一般エラー、正常完了・途中close・明示取消後の監視回収も検証する。
IPv4とIPv6を含む。単体試験の500ms待機はCIのスケジューリング余裕であり、音声停止の測定値ではない。

実モデルは前回と同じspeech.cpp 0.9.0 / Irodori MF F16 / Vulkan0 / 48kHz mono。
最初の実装は50ms監視で測定し、p95目標の未達が分かった後に20msへ短縮した。両群を保存する。
独立PipeWireで最初の通常3回、取消、保持mute、server SIGKILL、再起動後の発声を試験した。
最初のSIGKILL→仮想マイク無音は81.605ms。通常初音は305.287 / 476.329 / 351.565ms、
取消37.259ms、保持mute39.418ms。初音はevent生成から仮想マイクの20ms read frameでの音検出まで。
別環境・別seedの前回値との速度比較や、モデル単体TTFAとは扱わない。

50ms監視の30反復は、中央値83.460ms、nearest-rank p95 125.246ms、最大126.104ms。
全30件の250ms条件と新発話による回復を満たしたが、設計のp95≤100msには未達だった。
この群のrunnerの`passed`は個別250ms判定に限り、目標全達成として扱わない。
20ms版のrunnerには30件のp95判定も追加した。遅い尾を合格で隠さない回帰テスト4件をRED→GREENで検証した。

監視のCPU小試験は、同一Python HTTP fixtureで各間隔3秒×3回を、順序を入れ替えて実行した。
監視thread自身は50msで1コアの0.092〜0.110%、20msで0.157〜0.202%。
Python serverを含むfixture全体は各0.413〜0.476%、0.797〜0.858%だった。
これは実speech.cpp server、GPU、音声driver、VRChat/FPSの増分コストではない。
新規PCM bufferはなく、通常の1発話workerでは監視threadと同時probe socketを各1個だけ追加する。

音声suiteは**180 PASS**、Ruff PASS。既定の全体pytestは従来と同じ80ファイルで依存不足のcollection error。
全体のテスト合格とは扱わない。独立レビューは監視の寿命・取消競合・要求分離に問題を指摘しなかった。
レビュー担当自身はpytestを実行できておらず、実行結果は本作業の記録に基づく。

最終20ms監視の30反復は**全件停止・新発話での復旧に成功**した。

| 監視間隔 | 故障試行数 | 中央値 | p95 | 最大 | 判定 |
|---|---:|---:|---:|---:|---|
| 初期50ms | 30 | 83.460ms | 125.246ms | 126.104ms | p95目標未達 |
| 最終20ms | 30 | 81.446ms | 83.491ms | 124.619ms | p95≤100ms、最大≤250msを満たす |

始点は試験serverをkillする直前、終点は2秒以上続く無音区間の最初のread。
同一monotonic clockだが、20ms frameとOS schedulingの影響を含み、小数桁を物理精度とはしない。
同一モデル・経路の連続する2群で、seedや背景負荷は統制していない。対応のある比較や上限保証とは扱わない。
最終群の観測は27,635 frame、100ms超read間隔0、最大44.634ms。全30回の要求エラーは`server_unavailable`。
通常発声1回と復旧発声30回は、各要求で生成したPCMと仮想マイク録音を照合して各1回を確認した。
最終群の明示取消は81.212ms、保持muteは37.513msだった。

[混合経路PoC](../../tests/voice/listener_mix_poc.py)も最終版でPASS。
実HTTP経由の880Hz TTS代替音と別producerの440Hz VC代替音を同時に流し、listenerを閉じた。
TTS音は84.817msで消え、故障操作後から約2秒の確認終了まで105 frameすべてでVC音を検出した。
native gateとendpoint identityは保持され、明示的な全体muteでは両経路が無音になった。
これは実VCモデルの検証ではない。正弦波の周波数判定と実TTSの非ゼロ判定は別なので、遅延標本を混ぜない。

[全群の測定JSON](measurements/2026-10-27-tts-listener-fix.json)と
[故障60回のtimestamp CSV](measurements/2026-10-27-tts-listener-faults.csv)に、目標未達の初期群を含めて保存した。
raw WAV/PCM・serverログはgitignore対象の`tmp/tts-listener-fix/`に留める。
今回起動したspeech server計64 processの終了と、ホストの旧P1既定デバイス・音声3サービスの維持を確認した。
ホスト設定、VRChat設定は変更していない。

## 再実行

Linux、既存モデル・speech binary・ビルド済みnative gate・PipeWire/WirePlumberを用意して実行する。
OSの既定音声設定は変更せず、実マイクを録音しない。

```sh
uv run --no-project python -m pytest -q tests/voice
uv run --no-project python tools/live_tts_acceptance.py \
  --model /path/to/existing-Irodori-MF-F16.gguf \
  --private --samples 1 --crash-repeats 30 --output /tmp/tts-listener-new
uv run --no-project python tests/voice/listener_mix_poc.py --output /tmp/tts-listener-mix-new
```

runnerは各faultの無音化が250ms以内かを個別判定し、30反復時はp95≤100msも要求する。
診断用の12秒idle待機だけで`passed`にしない。以前の測定JSONやその判定は書き換えない。
各fault後は新serverを起動し、新発話の音声を照合して回復を確認する。

## 残る限界

- listenerが開いたままのHTTP connection単独故障、モデル停止、proxy経由の故障は早期検出の対象外。
- portを即座に再利用する再起動や別processを識別しない。監視周期の間に復旧すると見逃す可能性がある。
- TCP connect成功はモデルの健全性を意味しない。OS schedulingがあるため20msを検出上限とは呼ばない。
- 音声queueの総量を制限した変更ではない。通信停止・メモリ圧迫・長文の別試験は引き続き必要。
- WindowsのAPIは共通だが、実機・blocking audio writeの停止時間は未検証。
- 本書は独立経路の検証であり、VRChatの限定再試験は後続レポートに分ける。実VC、HMD、全VRCT UI/APIは未検証。
