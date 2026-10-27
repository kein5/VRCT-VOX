# P2外部入力の固定接続 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax.

**Goal:** 明示選択したsourceを独立VC入力へ接続し、停止・切断・親終了で閉じる、モデル不要のLinux基盤を作る。

**Architecture:** 既存managed graphはそのまま。PCMはowned pw-loopback、Pythonは選択identityと接続状態だけを制御する。streamをmute生成し、graph検査後にidentity-bound gateで開く。engine readinessとは区別する。

**Tech Stack:** Python3.11/uv、system PipeWire/WirePlumber、既存C gate、libc parent-death signal、pytest。

**Spec:** [機能仕様P2](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)、[ADR006](../../voice-stack/adr-006-external-source-health.md)。

## Global Constraints

- モデル不要。VCソフト・重みの取得/起動なし、実機hardwareのcaptureなし。実音声変換の合格とは言わない。
- 既存OSC/history/翻訳/TTSの形式・動作を変えない。最終仮想マイクを削除しない。
- sourceはcookie/serialで固定。名前だけの同名置換、既定fallback、勝手な再開は禁止。
- PCM処理はOS経路内。Python callbackにHTTP/推論/PCMqueueを追加しない。
- 非Linux import可能、backend実行はunsupported。Windows実装・P2全体/UI受入れは後続。
- 親thread終了もlauncherの停止条件。専用制御threadがchildを作成して継続所有する。

## Review Focus

- sourceまたはdaemonの置換が起動前後に起きても、mute開始とcookie/serial検査で別入力を流さない（Task1/2）。
- stopとstart/unmuteの競合で古いrunが再開しない（Task2）。
- processが存在していてもlink喪失・誤接続・観測失敗をhealthyとしない（Task2）。
- caller/制御threadの終了時にowned pw-loopbackだけを終了し、無関係なprocessやTTSを触らない（Task1/3）。
- sourceの存在を実VCの変換成功やWindows対応へ読み替えない（Task2/3・報告）。

### Task 1: identity-bound stream gateと親終了launcher

**Files:** Modify `native/voice-gate/main.c`, `tools/build_voice_gate.py`; Create `native/source-bridge/main.c`, `tests/voice/test_source_bridge_native.py`。

**Interfaces:** 既存`vrct-voice-gate COOKIE SERIAL MUTE`は維持。optional第4引数32桁lowerhex IDがある場合のみ`vrct.source-bridge.<id>.playback`、class`Stream/Output/Audio`、marker`vrct.source.bridge=v1`を対象にする。既存sourceは従来marker/classのまま。新launcher`build/vrct-source-bridge PARENT_PID [pw-loopback args...]`は固定`pw-loopback`をexecする。親PIDを前後照合し、PR_SET_PDEATHSIG=SIGKILL、失敗時はexecしない。

- [x] RED: 不正/不足引数・正しいbridge IDのCLI検証、managed旧契約維持、別marker/class/name/serial拒否を試験。launcherは既に死亡した親・親通常終了・SIGKILL・親thread終了でchild残存なしを実processで検査。Expected未実装FAIL。
- [x] 最小拡張とlauncherを実装し、build scriptで両binaryをcc -Wall -Wextra -Werror構築。
- [x] GREEN: nativeテストと既存gate関連をuv pytestで実行。実graph試験はprivate_graphだけ、marker不一致時mute値が変わらないことも確認。
- [x] 関連回帰・Ruff/diffチェック。`feat(audio): bind source bridge gate and lifetime`としてローカルcommit。

### Task 2: 非同期source bridge制御

**Files:** Create `src-python/models/audio_routing/source_bridge.py`, `tests/voice/test_source_bridge.py`。

**Interfaces:** frozen `Endpoint(cookie:int, serial:int, name:str, media_class:str)`; `select_source(graph, name)->Endpoint`はAudio/Sourceのみ、duplicate/managed final sourceを拒否。`SourceBridge.configure(source:Endpoint)`はまずstopし、音声を開かない。`start()`は専用threadを開始、`stop()`は世代失効・child停止を即要求、`close(timeout=3)->bool`は終了確認。`health()->dict`は`requested, active, pending, error, generation, conversion_verified=False`を返す。既定inactive、configure/start明示までPW接続なし。

Consumes: Task1 binaries。destinationは既存`vrct.managed.vc`、Audio/Sink・vrct.managed.route=v1。sourceとsinkのcookie/serialを固定する。owned両stream名は`vrct.source-bridge.<id>.capture/playback`、dont-fallback/reconnect/move=true、linger=false、playback初期mute=true。graphの実linkを確認するまでunmuteしない。

- [x] RED: source absent/duplicate/class不正/managed feedback、epoch変更、同名serial変更、linkなし/別target、process終了、query失敗、stop中start、unmute待ち中stop、stale worker、新start明示まで復帰しない、非Linux拒否をfake process/graphで再現。modeやengine readyは捏造しない。Expected未実装FAIL。
- [x] 制御threadでbounded graph query、起動deadline3s、monitor周期0.1s、gate timeout2.5s、child terminate0.5s→kill0.5s。APIは長い処理をlock内で行わずstopの世代失効を妨げない。stop/故障は最終sourceとTTSへ触れない。
- [x] GREENと関連voice回帰。`feat(audio): control explicit source forwarding without fallback`としてcommit。

### Task 3: モデル不要の実OS受入れ

**Files:** Create `tools/source_bridge_acceptance.py`, `tests/voice/test_source_bridge_acceptance.py`, report under `docs/voice-stack/`。

**Interfaces:** CLI `--output NEW_DIRECTORY --runs N` default3,1..30。private_graphと合成音のみ。reportにはsource/出力のidentity、操作→source read無音確認の境界、全試行、capture進行/欠測、`real_vc_verified=False`、`host_audio_changed=False`を含む。rawPCM既定保存なし。

- [x] RED: partial failureでもreport保存/cleanup、既存出力dir拒否、invalid runs拒否、reader死亡/欠測を無音成功にしないテスト。
- [x] 実装し、通常選択→停止、source削除→禁止fallback音が流れない→同名再作成でも停止保持→明示再選択、sink削除、親/制御thread停止を実OSで試験。source440Hz/禁止1760Hz/TTS880Hz、停止中TTSが継続することも観測。
- [x] uv CLI実行Expected全ケースPASSか原因を記録。未解決ならimozuru調査後にユーザー指定通り中断。性能p95を少数試行から主張しない。
- [x] 関連suiteと既定全体suite（既知16失敗は別記）、共有するmetadata/報告、残るP2 UI/engine/Windowsのゲートを更新してcommit。
- [ ] 一回の独立final review。Critical/Importantのみ一回のRED→GREEN修正、Minorは記録。継続作業のためworktree/ledger保持、push/mergeなし。

## Pre-flight

Task1 gate名/marker/CLIはTask2の生成値と一致。Task3はTask2公開APIと既存ToneCaptureの連続性検査を使用。
起動muteの実動作は`tmp/voice-resume/research/p2-vc/muted-bridge-spike.json`で先行確認済み。
P2全体のprovider/UI/本物の変換/Windowsをこの部分計画で完了扱いにしない。
