# Seed-VC 実機PoC（2026-10-28）

**B「外部推論＋OS音声経路」で、実VCから私有仮想マイクまでの出力と故障停止を確認した。P2全体の完成・Seed採用決定ではない。** 物理マイク、VRChat、聴感品質、語頭の保持、長時間運転、GPU競合、Windowsは未検証。

実装は [integrations/seed_vc](../../integrations/seed_vc/README.md)。[機械可読結果](seed-vc-poc-results.json)、[モデルロード記録](seed-vc-runtime-report.md)、[同意済みartifact](seed-vc-acquisition.json)を参照。固定5モデル1,523,519,558 bytesと、ユーザーが提示した参照音声を使用した。取得・参照音声の同意は取得済みで、新規録音はしていない。私有音声・重み・原音パスはGitに含めない。

## 実行経路と測定範囲

```mermaid
flowchart LR
    F[既存の合成試験音声] --> W[別プロセスのSeed-VC\nモデル・参照音声はローカル限定]
    W --> G[変換状態・PCM・期限の検査]
    G --> P[私有PipeWire音声ソース]
    P --> B[既存SourceBridge]
    B --> M[私有仮想マイク]
    M --> C[継続captureと無音検証]
```

入力は4.88秒の既存P1合成音声を実時間でブロック供給したもの。モデルは3ブロックwarmup後、VADと音声バッファを再初期化する。許可された参照WAVは14.52秒、48kHz mono。実際のprompt設定は先頭3秒。RTX 4080 SUPER、torch/torchaudio 2.10.0+cu128、固定engineと依存lockを使用した。

`processing_ms`は変換呼出しの開始から終了まで。リサンプル・pipe送信・OS接続・capture readを含まない。入力→readは、入力ファイルの振幅閾値超過時刻を実時間供給に対応させた時刻から、仮想マイクの20ms captureの最初の閾値超過readまで。内容の対応・聴感は検証しておらず、生成ノイズも検出し得る。**物理入力→VRChatのE2E遅延ではない。** native callback用の2block出力ringは今回使用していないため、その推定式を測定値の説明に使わない。

## 比較結果

| 設定・条件 | 実block / right | 仮想入力開始→最初のread | 確認状態 |
|---|---:|---:|---|
| 固定engine既定、発声時に経路接続 | 240 / 2000 ms | 2517–2559 ms、4試行 | 出力・停止は成功、低遅延目標未達 |
| VAD修正、発声時に経路接続 | 80 / 20 ms | 464–470 ms、5試行 | モデル単体時間より長い接続待ちを含む |
| VAD修正、無音時に経路準備 | 80 / 20 ms | 295–337 ms、5試行 | 変換前はPCMを渡さず無音を確認 |
| 同条件、故障・対照を拡充 | 80 / 20 ms | 337–340 ms、7試行 | 下表の停止試験と同時測定 |

既定設定のofflineモデル単体はp50 36.82ms / p95 38.43ms（最初の3ブロック除外）。この値を入力→出力の値へ置き換えていない。短い単一入力の結果であり、仕様の物理入力p50 <250ms / p95 <400msの合格とは判定しない。特にp50目標、品質、混在負荷は未達または未検証。

OS経路を先に準備するのは、このsupervisorだけが検査済みPCMを書き込む私有ソースに限る。モデルreadyだけではPCMを出さない。経路activeと変換成功は別状態で、既存製品UIの`conversion_verified=false`は変更していない。任意の外部VCソフトへこの保証を一般化しない。

## 停止・故障・負の対照

最終80/20ms試験では、各処理後に2秒以上の連続無音を確認した。captureのEOF・読み取りエラー・100ms超の欠測は0、最大read間隔47.83ms。各試行の子プロセスと私有graphは終了した。

| 操作 | 最初の無音readまで | supervisorの停止・出力close完了まで |
|---|---:|---:|
| 停止 | 38.72ms | 40.04ms |
| bypass要求 | 127.31ms | 53.58ms |
| 実推論例外 | 123.31ms | 58.00ms |
| 推論プロセス強制終了 | 40.79ms | 40.95ms |
| 推論の進行を停止 | 124.47ms | 1006.44ms |
| 意図的な処理遅延 | 126.62ms | 333.36ms |

後列はコード上のclose処理完了時刻であり、別のハードウェア測定ではない。進行停止時はpipeが空になって先に無音となり、1秒のpacket期限で経路を閉じる。この2つの時刻を混同しない。結果JSONの`gate_closed_ms`はこの後列を表す。

- bypass・推論例外・EOF後は閉鎖し、自動再開しない。停止中に返った結果も破棄する。
- 推論の前後で予定時刻から2blockを超えた結果を破棄する。意図的な遅延で`worker_overload`を確認した。
- 部分packetが届いたまま止まるケースもtimeoutする。captureの停止を「無音」と誤判定する5種類の負の対照を既存観測器で確認した。
- 停止命令を送らない同じ入力の対照では、2.1秒間変換音声が継続した。停止試験の無音を自然な発話終了だけで説明しない。
- 実モデルへの全無音入力では、converted block・非無音sampleとも0。通常の3プロファイルでは変換音声が出た。
- 入力と完全に同一のPCMを返すfake engine、mode変更、NaN、握りつぶされた例外を拒否した。任意の原声混入を音響的に識別する万能検出器ではない。
- 既定入力には1760Hzの禁止toneを配置した。停止後の無音窓では検出なし。発声中には変換音声の倍音と区別できない少数frameの検出があるため、発声中のtone混入率をゼロと主張しない。経路のidentity/fallback保証は既存SourceBridgeの別試験も参照する。

## 原典調査で直した点

固定engineは発話未検出時に毎block VAD cacheを破棄していた。FSMN設定の200ms窓・150ms発話開始閾値に対し、180ms／80msの両設定が実モデルで全無音になった。idle時だけの無条件resetを除くと、同一モデル・入力で両設定が成功した。既存の実時間10秒ごとのresetと明示的なバッファ再準備は残している。長時間のreset境界は未検証。

一次資料は[固定engine](https://github.com/jiaheguo521/seed-vc-realtime/blob/58d0ca372cc76f60a798d9f84611f053f9029f3a/realtime_vc_engine.py#L923)、[承認済みVAD設定](https://huggingface.co/funasr/fsmn-vad/blob/df20e6b30c653645fa4ff125cacfcabd1020a669/config.yaml)、[固定上流の設定例](https://github.com/Plachtaa/seed-vc/blob/51383efd921027683c89e5348211d93ff12ac2a8/real-time-gui.py)。imozuruの2検索役が独立に追跡し、原文・hash・行番号と6抜粋の照合結果を`tmp/voice-resume/research/p2-seed-latency/`へ保存した。調査は直接参照のみ、検索queryは0本。

## テストと残件

実モデル関連59 PASS（3設定・無音対照・5モデルロード・VAD・入力検査）。実経路7ケースPASS（61.41秒）。音声関連352 PASS / 8 opt-in SKIP / 1 warning。既定suiteは1173 PASS / 16 FAIL / 6 SKIP / 46 warnings、14.51秒。失敗名集合は既存基準と完全一致し、一覧は[前段報告](seed-vc-runtime-report.md#unchanged-default-suite-failures)に保持している。全suiteがgreenという主張ではない。

このPoCは外部GPL adapterと固定モデルの検証まで。製品の物理capture/converted切替・能力確認・UI統合、P3 ASR、P4翻訳発声、P5 Windows/配布・長時間/競合試験は引き続き残る。VAD判定前の語頭が失われていないか、参照声に近いか、雑音下での動作を次の品質ゲートにする。短い数値だけで低遅延profileを製品既定にしない。

GPL engine/adapter/model、Apacheモデルと依存ごとの配布条件を保持し、モデルを製品へ同梱していない。これは最終ライセンス監査ではない。push、公開release、PR、上流への打診は行っていない。
