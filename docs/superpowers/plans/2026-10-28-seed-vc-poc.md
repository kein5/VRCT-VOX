# Seed-VC 実機PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 同意済み固定モデルを検証可能な形で取得し、隔離した外部Seed engineでロード・VAD互換・変換と故障停止を実測する。
**Architecture:** B（外部推論＋OS音声経路）のまま。本体Controller/UIへ未知のconverted状態を追加しない。モデル取得helperは明示manifest限定。GPL対象engine/PoC adapterはMIT本体から別ディレクトリに置き、固定checkoutと対応source/patchを記録。推論時はlocal file限定。
**Tech Stack:** uv/Python3.11、PyTorch CUDA runtime、固定Seed-VC、FunASR、私有PipeWire、既存SourceBridgeとcapture観測器。
**Spec:** [承認済みPoC提案](../../voice-stack/vc-engine-poc-proposal.md)、[固定artifact](../../voice-stack/seed-vc-poc-artifacts.json)、[仕様§8/P2](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)。

## Global Constraints

- ユーザーが2026-10-28に5モデル約1.524GBの取得とPoC実行を明示承認。参照音声のフォルダーも提示済み。再確認しない。
- manifest外のモデル・公開サンプル音声・remote codeを自動取得/実行しない。私有音声・重みはgitignore対象tmpに保管。
- 既存venv/ドライバー/ホスト既定音声/VRChat/WiVRn設定を変更しない。uvでPoC runtimeを隔離。
- モデルロード成功、変換block成功、OS経路active、聴感品質、end-to-end latencyを区別。未測定の値・性能目標合格を捏造しない。
- raw reference/outputはローカル限定。共有報告はhash・長さ・数値、音声本文や個人pathを含めない。
- エラー/bypass/停止時は原声を出さない。私有graphで既定入力の禁止toneを監視する。
- Windows、物理mic、VRChat、混在負荷、公開/上流打診はこのPoCの合格と別。PR/outreachはユーザーの明示指示まで禁止。

## Review Focus

- manifest path/size/hash不一致、途中取得や既存壊れたファイルを成功として使わない。
- import/model loaderの別branchが承認外モデルやremote codeをネットワークから取らない。
- GPU/VADロードが成功しても入力監視bypass・推論失敗を変換成功と表示しない。
- fault/stop時にworkerやPCM queueが残り、原声/古い生成音が出ない。
- 音声同意・license境界と実測の開始終了点を原典/実行環境ごとに保持する。

### Task 1: 固定artifact取得と整合性

**Files:** Create `tools/seedvc_artifacts.py`, `tests/voice/test_seedvc_artifacts.py`; Modify proposal/manifest consent status; raw `tmp/voice-resume/seed-vc-poc/`。
**Interfaces:** manifestのrepo/revision/rfilename/size/LFSsha256またはGitblob SHA1を検査。`fetch_artifacts(manifest, root, opener=...)`はallowlist各fileを一時file→検証→atomic rename。既存fileも再検証。結果は全file SHA256/サイズ/固定URLだけ（signed redirect URLは記録しない）。CLIに明示`--consent-reviewed`（実行者が今回の同意を反映）。

- [x] RED: 正常hash、破損/短い/超過body、取得例外、既存破損、path traversal/symlink escape、未同意CLI、余分なfileを取らない、JSON/サイズ合計をテスト。Expected: 新APIがなく失敗。
- [x] 最小helper実装、GREEN、Ruff/diff。Expected: 全てPASS。
- [x] ユーザー同意に従い実取得し全12file/1,523,519,558bytesを照合。参照音声metadata/hashをローカル記録し、適切な長さの試験用copyを用意。Expected: manifest外取得0、private audio tracked0。ローカルcommit。

### Task 2: 隔離runtimeとoffline engineロード

**Files:** Create `integrations/seed_vc/`内GPL表記adapter/requirements/README（必要なら固定upstream patch）、`tests/voice/test_seedvc_offline.py`、raw環境/依存lock/checkout。
**Interfaces:** adapter引数はengine root/assets root/reference path。必要全fileを確認してから重いimport。local Seed/checkpoint、CAMPPlus/HiFT、XLSR、HF FSMN-VADを明示。download functionsを汎用許可しない。network禁止時に追加取得を試みるloaderは失敗。voice statusをモデルready・VC active・bypass・failureに分ける。

- [x] RED: local resolverのunknown repository/file/欠損/改変拒否、remote path拒否、reference長さ不正、必須state欠損/shape不一致拒否（failure/bypass/stopはTask3の実workerで検査）。Expected: 新adapterがなく失敗。
- [x] 固定engineソースと必要コードのみ取得（サンプル音声不要）、公式対応組合せをuvで隔離し依存lockを記録。requirements不整合はimozuruで原典を追い最小変更をledgerへ。Expected: GPU/torch実動作を確認、既存環境無変更。
- [x] offline loader/必要patchを最小実装しGREEN。実5モデルロード・VADの複数chunk入力を試験、ネットワーク取得0を観測。Expected: ロード成功または具体的な失敗記録。成果と互換差分をcommit。

### Task 3: 実変換block・私有仮想mic・故障試験

**Files:** Create PoC runner/acceptance tests、docs voice-stack report/measurements。必要adapter調整。
**Interfaces:** 許可ある参照音声と既存合成試験音声を使い、engine block処理と出力PCMを別processで私有経路へ。source bridge経路healthとengine変換healthは別。bypass/推論exception/stop/プロセス終了の合否をcontinuous captureで確認。

- [x] RED: 実adapterのfault/stop、入力そのまま出力、死んだcaptureを検出するnegative controlsを先に実行。Expected: 未実装fault閉鎖や観測不足を検出。
- [x] 実checkpoint変換→私有仮想マイク、モデル単体/OS read時刻を別に測定。GPU/VRAM・warmup・chunk設定・低遅延未達/聴感未検証を記録。Expected: 合否が明確で原声fallbackなし。real-time throughput未達なら合格とはしない。
- [x] 回帰（関連+既定known16比較）、ライセンス/同意/測定境界を報告しcommit。必要なら問題をimozuru調査、それでも解決不能ならユーザー指定通り中断する。
- [x] 一回の独立review、Critical/ImportantのみRED→GREEN一修正pass。Minor保留。全機能継続のためworktree/ledger保持、push/merge/PRなし。

## Pre-flight

Task1→2: 取得配置とmanifest SHA256をoffline loaderが同じ規則で読む。modelカードの期待hashと実hashを区別。
Task2→3: engineモデルreadyだけでは音声gateを開かず、実block成功・mode・faultを観測する。既存SourceBridgeは変換証明をしない。
Task1→3: reference/input/outputをtmp限定にし、公開measurementにはhash/durationだけ移す。
Task2の外部GPL adapterは未採用のPoCで、既存MITアプリへの取り込みは後続判断。構成追加の費用を実測後に比較する。
