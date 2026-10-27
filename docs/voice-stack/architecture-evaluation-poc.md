# 音声アーキテクチャの検証用PoC設計

状態: **未実装・未実行の試験計画**。2026-10-27の[設計評価](architecture-evaluation-2026-10-27.md)と[ADR 004案](adr-004-audio-integration-boundaries.md)を反証するためのもの。今回の作業でモデル取得、driver設定変更、録音、負荷試験は行っていない。

## 共通の測定契約

- 同一モデル・hash・入力・seed方針・sample rate・出力先・負荷でA/B/Cを比較する。異なるengine間の差をIPCの差として説明しない。
- WindowsのOS build/driver/host API/virtual cable版、LinuxのPipeWire/WirePlumber版、GPU/driver/VRAM、VRChat desktop/VR、WiVRn/HMD接続有無、FPS/frame timeを記録する。
- cold/load/warmを別群にする。最初の確認は各群30試行、採用判断用は代表コーパス・言語・長さ・負荷ごとに原則100試行以上を提案する。試行数自体でp99の安定性を保証しない。VCのframe標本は相関するため独立な発話・セッションも数える。
- 総試行数、成功、取消、timeout、失敗、境界欠測、除外理由を残す。失敗を0msにせず、成功率と成功時のnearest-rank分布を並べる。p99は標本数と最大値も併記し、比較順を交互化して温度・負荷の偏りを抑える。
- monotonic clock内の差を原則とする。UI/プロセス/device間はclock ID・校正方法・誤差を記録。cross-clockの負値を0へ丸めない。
- 非ゼロsample、閾値を超えた音声開始、最初の意味ある発話を分ける。VCで波形が変わるため、無変換経路による計測器校正と、対応可能な音声特徴・試験発話での評価を併用する。相関不成立は欠測として残す。
- 本文や原音をtelemetryへ送らない。信号試験は合成音を使い、実声・参照声・録音保存は従来の同意範囲を守る。VRChat内蔵テスト・private instanceで確認し、他人への試験送信を前提にしない。
- Pythonハーネスを後日作る場合は`uv`を使う。通常のデスクトップdefaultを変更しない隔離graphを先行し、その後に利用者が選択した実経路を検証する。

## PoC一覧

| ID / 目的 | 最小構成・刺激 | 自動化する観測／成果物 | 合格・判断条件 |
|---|---|---|---|
| PoC-1 全経路の停止と誤出力防止 | 合成mic、VC代替信号、TTS信号、別のdefault候補を区別可能な信号で用意。TTS取消・全体mute・mode変更・engine終了・仮想endpoint削除・再作成・物理device消失・VRChat再起動 | graph snapshot、実target、経路別generation、最後の対象信号、無音区間、禁止信号カウンター。各故障30反復。後段で実Windows/LinuxとVRChatの選択も確認 | 禁止信号0・旧世代再生0。TTS取消後はTTS信号0かつVC継続、全体mute後は全信号0を2秒確認。対象の停止目標p95≤100ms/最悪≤250ms。source消失時のconsumer挙動が不明なら未判定。B失敗ならCで同一試験 |
| PoC-2 UIからのTTSと取消 | fake翻訳を0/0.5/6秒にし、Mainの3 workerを占有。原文/訳文を送信。HTTPはheader待ち・body待ち・遅着・切断を再現 | UI submit、受付、翻訳、publish、request、first byte/write、停止のtrace。旧OSC/history/WebSocket契約の検査。短文・長文・空訳・多言語・同一ID/異なるID | 原文TTSが翻訳待ちを含まない。訳文のみモードは空訳で無音。重複・古い世代の発声0。UI→write仕様350/800msを実TTSで評価。fake所要時間を推論速度として使わない |
| PoC-3 直接VCとAPI成立性 | Windows VCClientの採用edition、Linux候補、Seedをversion/hash固定。device所有方式から始め、必要なら実在するPCM APIを別比較 | 入力→仮想出力の時刻、engine処理時間、buffer age、drop/xrun、品質、CPU/RAM/VRAM。設定・モデル・driver・fallback動作・API capability一覧 | p50<250ms/p95<400msは目標。未達は未達と記録しモデル/条件を見直す。生声fallback・出力先自動変更を拒否できない構成は不採用。OS版で同一モデルを扱えない場合は別製品構成として評価 |
| PoC-4 ASR finalとGPU競合 | mic/speaker別session、server VAD、24kHz入力を用意。partial訂正・重複/逆順final・再接続・発話再開。VC＋TTSと同時実行し、単一ASRと分離ASRを比較 | 実音声終端、VAD commit、partial/final、翻訳表示、訳音声。モデル待ち時間、GPU load、FPS/frame time。誤切断・誤認識・重複出力も集計 | partial発声0、speaker再発声0、確定発話の重複0。final1.2秒/訳表示2秒/訳声3秒を目標評価。単一モデルで未達なら受付頻度・priority・モデル複製の費用を比較 |
| PoC-5 OS混合・clock・長時間 | VC＋typed TTS混合、訳文モード時VC抑制、monitor有無、異なるdevice clock、24/44.1/48kHz。Windows sharedとLinux graph、HMD接続を比較 | mix/gateごとの信号、実period/quantum、OS padding、buffer占有の時系列、再接続target、30分の遅延分布、xrun・CPU/GPU/VRAM・FPS | 既存音声共存、禁止信号0、crash0、滞留の継続増加0。ゲーム個別captureへ自身のTTSが混入しない。mix/duck/fan-outがOSで成立しなければCを比較 |
| PoC-6 配布・変更耐性 | モデルを取得せずmanifestと既存build検査から開始。選ぶengine/weight/codec/driverのversion・由来・hash・条件を追跡。API変更fixture、Linux headless/GUI import境界を点検 | artifact台帳、ライセンス原典リンク、禁止OCR検査、契約試験、OS capability表、旧機能OFF回帰記録 | 同梱全件の条件確認、禁止物0、旧payload変更0。条件不明・実体不明は「同梱可」にしない。GUI未起動ならLinux製品対応は未完了 |
| PoC-7 A/B/Cの必要性 | Bの実traceで支配的な待ちを特定した後、同じ推論・同じsinkでCの最小出力worker、必要ならAのspeech C APIのみを比較 | paired trace、IPC区間、first useful audio、停止tail、fault blast radius、資源差、保守する依存一覧 | モデル支配ならIPC変更を選ばない。CはBの停止/所有問題を実際に改善したとき採用。AはIPCが目標未達の主因で、改善が誤差を超え、互換性・license条件も満たすときだけ再審議 |

## 具体的に完成させるPoC成果物

PoC-1/2はモデルなしで失敗を再現できる自動試験、PoC-3/4は版固定した実engineの比較レポート、PoC-5はOS別の経路図と30分trace、PoC-6はartifact台帳、PoC-7は同条件比較のADR更新材料を成果物とする。新しい実装ファイル名・公開APIは今回確定しない。

将来のログは`run_id / session_id / utterance_id / generation / source / event / monotonic_ns / clock_domain / outcome`を基本とし、音声時間のbuffer占有量と出力先IDを添える。本文をID代わりに使わない。接続ready、モデルwarm、gate-open、発声中を区別する。

取消の適用範囲もログに残す。既存`stop_voice`はTTS取消で、次の新TTSを受け付け、VCとASRは継続する。全体muteは別操作で、明示解除まで全体gateを保持する。TTS単独故障でVCを止めないこと、接続復旧・新TTS・mode選択だけで全体muteが解除されないこともPoC-1/2の契約試験に含める。

Windowsのprocess loopbackは受信音声をprocess treeで分離する候補であり、virtual mic生成手段ではない。公式sampleの条件はbuild 20348以上。対応外OSをデスクトップ全音声captureへ黙ってfallbackさせず、明示設定と別のループ試験を必要とする。[Microsoft sample](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)

## Fitness functionと責任

今回のdecision owner候補はリポジトリ保守者／依頼者、試験作成・実行担当は次の音声統合担当者。これは役割の提案であり、担当者の引受けや採否は未確定。コード変更の前に担当を記録する。

| 確認対象 | 実施時期 | 必須証拠 | 欠測・失敗時の扱い | 判断を変える人 |
|---|---|---|---|---|
| OFF互換・発話世代・partial/final | 音声変更ごと、CI | contract testと対象commit | merge可能と判断する材料不足。旧試験を除外して通過扱いにしない | 保守者 |
| 取消・経路・fallback | audio/OS/driver/engine変更ごと | PoC-1の信号・graph・全試行結果 | 構成を有効にしない。B/C再選定 | 保守者＋実機担当 |
| 遅延・GPU競合 | 候補選定時、モデル/設定変更時、release前 | PoC-2〜5のraw trace、群別分布、失敗数 | 達成未判定。境界変更で閾値を満たしたことにしない | 保守者 |
| ライセンス・配布 | artifact追加時、release前 | manifest、原典、hash、build検査 | 条件不明のartifactは配布保留 | 配布担当／保守者 |

偽陽性の例は試験reader自身のbuffer遅延、clock校正不良。無変換の既知経路で校正し、原因が確定するまで未判定とする。偽陰性の例は専用graphだけの成功、同じ短文だけの反復、worker idleを無音とみなすこと。実VRChat・実device・異なる言語と長さ・混在負荷で補う。測定の除外・閾値の変更・例外には理由と期限を残し、ADRを更新する。

現段階の結果欄は全PoC **未実行**。過去のP1試験は[既存計測記録](benchmarks.md)として参照し、今回の試験結果として再利用しない。
