# ADR 004: 外部推論と音声経路の境界を条件付きで選ぶ

Status: **proposed**, 2026-10-27。承認・実装・実機確認は未完了。

Decision authority: リポジトリ保守者／依頼者。確認担当: 次の音声統合担当者（未割当）。

Scope: P1見直しとP2〜P5の音声統合。既存テキスト機能の全面再設計、独自virtual driver開発、クラウドサービス化は含めない。

Related: [評価書](architecture-evaluation-2026-10-27.md)、[確認用PoC・fitness functions](architecture-evaluation-poc.md)、[ADR 001〜003](decisions.md)。本提案だけで既存accepted ADRをsupersededに変更しない。

## Context

VRCTはReact/Tauri/Python構成で、P1は外部speech.cppと専用TTS threadを追加した。Linuxの部分経路とVRChat内蔵マイクテストは記録があるが、UI起点・Windows・VC/ASR混在・HMDの性能は未確定。原文TTSが翻訳後に投入されること、停止が一般dispatchを通ること、Windowsのblocking write、仮想endpoint消失時のconsumer側fallbackが課題として残る。

speech.cppはモデルごとに要求を直列化する。VC候補はOS/edition/API/モデル条件が異なる。外部processにしてもGPU競合と配布条件は自動解決しない。このため、現計画を前提にするのではなく責務・失敗時動作・実測で選定する。

## Decision proposal

1. **B: 外部推論＋OS音声経路を最初の検証対象として選ぶ。** Pythonに小さな制御の所有者を置き、既存OSC/翻訳/historyの契約は保持する。推論・HTTPを音声callbackやUIに置かない。
2. 直接VCはASR/翻訳/TTSから独立させる。原文TTSは入力検証とID確定後に分岐し、訳文TTSは選択した確定訳のみから生成する。部分認識・受信音声を既定で発声させない。
3. 停止とmode変更は一般処理キューの飽和から分離する。既存`stop_voice`はTTSのみを取り消し、直接VCとASRを継続する。次の新TTSは受付可能。全体muteは別の明示操作とし、全経路を止めて明示解除まで保持する。TTS別gate/generationと全体gate/mode世代を区別し、TTS単独故障や設定変更でVCを止めない。生成停止と対象信号の実出力停止を別に観測する。
4. 仮想endpointの寿命を推論から独立させる。故障時は無音、過去発話を再送せず、生声fallbackを行わない。OS/VRChatの再接続挙動を実機で確かめる。
5. **C: 専用音声processはBが契約を満たせない場合の第一代替。** capture/mix/gate/buffer/lifecycleに責務を限定する。汎用service busや共通engine SDKを先に作らない。
6. モデル・OSのcapabilityを実証する前に、すべてのVCを共通`feed(PCM)`で扱えるとは決めない。最初のdevice-owned方式と将来のPCM方式を区別する。

この決定はBの製品採用を確定しない。Bで全モードを実証するか、必要な範囲をCに移して再試験した後に、採用範囲を記録する。

## Alternatives and rejection reasons

| 案 | 現時点の判断 | 再検討条件 |
|---|---|---|
| A: 同一processへspeech C APIとVCを組込む | native障害・ABI・配布依存を既存sidecarへ広げる費用に対し、HTTP削減の価値が未測定 | 同条件traceでIPC/serializationが性能未達の主因と判明し、Aが誤差を超えて改善。旧機能・両OS・license条件も満たす |
| B: 外部推論＋OS経路 | 条件付きの第一PoC候補 | 全経路の無音化・停止・混合・capture共存が成立しなければ採用範囲を縮め、Cへ |
| C: 専用audio process＋外部推論 | いま全面導入はしない。責務隔離の必要性は具体的にあり、第一代替として残す | Bで停止期限・driver隔離・mix/duck・single captureを満たせず、Cの最小PoCで改善を示した場合 |
| WebSocket companionのみ | P1単体には簡単だが、直接VC・原音ASR・全mode停止の所有を解決しない | 要求が独立TTS companionだけへ縮小し、停止・発話ID契約を外部で満たせる場合 |

## Consequences

既存機能への変更を限定し、engineとモデルの選定を後から変更できる。一方で、OS別経路・engine版・外部virtual driverのサポート負担を受け入れる。BはOS任せで自動的に安全・高速になるわけではない。Windows mix/duckやLinux consumer再接続が成立しなければ追加開発が必要となる。

共有GPUの競合、モデルのblock/lookahead、先頭無音はprocess境界を変えても残る。性能未達がモデルに支配される場合は、Cへの移行で解決したことにせず、モデル・負荷・目標を再検討する。

engineと重みは初期にはユーザー管理を前提とし、追加取得・同梱を自動化しない。これは配布上の義務を免除する判断ではない。code/weight/vocoder/driverを個別に確認し、禁止OCR重みの既存除外を維持する。

## Confirmation and reversal

| 保全する性質 | 確認 | 条件・失敗時 |
|---|---|---|
| 互換性 | PoC-2/6、OFF時の旧契約・全回帰 | 旧payload破壊や機能退行なら設計を修正 |
| 誤出力防止 | PoC-1/5、禁止信号とconsumer target | 誤出力1件でもその構成を不採用。Cも同じ基準 |
| 取消 | PoC-1/2、UI起点→endpointで対象信号消失 | p95≤100ms/最悪≤250msは提案値。TTS取消はVC継続、全体muteは全出力無音を要求。未達なら原因を切り分け、Cまたは閾値の根拠を再審議。対象の無音継続は必須 |
| 会話品質・資源 | PoC-3/4/5 | 仕様のVC/TTS/ASR目標、30分の滞留・drop・FPS・VRAMを評価。作者値は合格証拠にしない |
| 複雑さの費用 | PoC-7 | CがBの問題を解かない、またはBが全条件を満たすならCを追加しない |
| 配布条件 | PoC-6のartifact台帳 | 未確認artifactの配布を保留。外部processだけで許諾を断定しない |

確認の詳細、測定母数・欠測・誤判定対策・担当役割は[PoC設計](architecture-evaluation-poc.md)に置く。次のレビュー時点はPoC-1/3完了時、engine/driver/model更新時、P4の混合採用前、release前。状態をacceptedへ変える際は、担当者・合格した構成・残る制限・生記録へのリンクを追記する。

## Current evidence and open items

確認済みなのはP1の限定経路とコード構造。[既存benchmarks](benchmarks.md)と[評価書の遅延監査](architecture-evaluation-2026-10-27.md#7-遅延の監査)を参照。新しいPoCは未実施であり、Windowsの停止・混合、VRChatのendpoint消失時動作、VC採用、GPU混在負荷、Linux GUI、配布物全件は未確定。
