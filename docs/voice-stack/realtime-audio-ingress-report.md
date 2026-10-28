# Realtime入力の連続変換・キュー検証（2026-10-28）

`realtime_audio.py`に連続PCMの24kHz化と同期capture→async通信の有界入力キューを追加した。
物理デバイスの選択・録音・UI字幕への接続はこの工程に含まない。
既存legacy recorder/providerは維持している。

入力は実rate/channel付きs16le、1chunk5–100ms。ステレオはfloat32で平均し、soxr1.1.0 HQで連続変換、最後にs16leへ量子化する。
出力0/可変長を許容し、最大20msずつ既存Realtime producerへ渡す。
入力先頭sampleのtimestampをsample位置で換算するため、キュー滞留・変換待ちを送信時の時刻で隠さない。
入力timestampが末尾のOS callbackでは先頭への換算が別途必要。

キュー上限20items/200ms、受付と送信前のage上限250ms、native pending上限200ms。
これは各段の限界であり、合計が250ms以下になるという保証ではない。最後のage検査で古い音声はセッションを止める。
overflow、形式変更、未来/非単調timestampでも残PCMを破棄する。stopはfilter tailをflushせず破棄する。
そのため正常な発話終端を認識させる呼び出し側は、停止前に自然な末尾無音を供給する必要がある。

## 自動検証

14件RED（module未実装）→GREEN、追加3件を含め単体17 PASS。
44.1/48kHzの1kHz保持、18kHzのalias抑制、異なるchunkサイズの連続性、timestamp換算、ステレオheadroom、無音、停止、native backlog、queue時間/件数上限、滞留後の期限切れ、取消・送信失敗を検証。
変更範囲Ruff/diff PASS。関連524 PASS / 11 opt-in SKIP / 7 warnings（16.86秒）。

実speech.cpp0.9.0/ReazonSpeech GPU/Silero CPUへ、元の48kHz合成音声を20msごとに供給。
production ingressを通した2sessionと別無音sessionを、外部ネットワークを切ったnamespaceで試験した。
単体＋実試験 **18 PASS（8.02秒）**。
[実結果](realtime-audio-ingress-results.json)に各sourceのpartial/final数と予定capture先頭→feed時点の最大ageを記録。
停止後pushは拒否され、pump終了時にRealtime clientもclosedとなる。
新規録音は行っていない。認識精度・物理デバイス・Windows実機の合格を意味しない。

## 変換単体の計測

[計測JSON](realtime-audio-resampler-results.json)は60秒相当の合成PCM/3000chunkを待ち時間なしで処理したもの。
最初の非空出力まで40ms分の入力、native pending最大38.333ms（44.1/48k共通）。
process呼び出しp95は0.02174ms/0.01266ms。計測にはOS capture、queue、network、ASR、UIを含めない。
60秒の実時間動作や混在GPU負荷を検証した値ではない。物理発話終端→字幕p95は未測定。

## 依存と残件

[ライセンス台帳](licensing.md)に固定wheel、LGPL/PFFFT通知と最終配布前の対応source/置換条件・nanobind noticeの残件を記録。
新機能を選んだ時だけsoxrをimportする。未導入時の設定UIエラー表示は次の統合工程で扱う。
imozuruの原典6本・照合済み引用8件・検索2語30hitsは`tmp/voice-resume/research/asr-resampler/`。

次工程はOS captureとUI/既存final処理への接続。P3全体、P2聴感、P4翻訳発声、P5Windows/配布/混在負荷は引き続き未完了。

既定suite1173 PASS / 16既知FAIL / 6 SKIP / 46 warnings。失敗名集合は直前と一致。


## 独立レビュー後の停止修正

Critical0/Important1/Minor0。送信が詰まるとclose/overflowが通信セッションまで届かない問題を、
実producerと停止した模擬socketで2件RED→GREENにした。
capture threadからthread-safe通知し、pumpはworkerと停止通知の先着を待つ。
停止時は先にclientの状態と未配信結果を閉じ、その後worker/waiterをcancel/gatherする。
実モデル込み **56 PASS（11.22秒）**、関連 **526 PASS / 11 opt-in SKIP / 7 warnings（17.27秒）**。
独立レビューの追加実行はしていない。

`close()`は入力を即座に拒否し、loopへ停止を予約する同期操作。停止完了境界は`await pump`。
UI側は停止操作時にnamespaceを無効化し、予約から完了までの結果を公開しない必要がある。
物理capture/Windows/UI/final routing/長時間負荷と最終binary license判断はレビュー対象外で、次工程のゲートに残す。
固定原典と引用照合済み記録は`tmp/voice-resume/research/ingress-stop/`。
