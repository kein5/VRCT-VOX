# Native voice entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本番TauriとPythonをLinuxで起動し、実設定保存・テキストTTSの経路を検証する。

**Architecture:** 既存Tauri/React・Main/Controllerを維持し、Windows専用起動処理と依存だけをOSで分ける。推論は既存の外部speech.cppとする。Linuxを成功したfixtureとして偽装せず、本番初期化を通す。

**Tech Stack:** Rust/Tauri 2.5.1、React、uv/CPython 3.11、PipeWire、既存HTTP PCM。

**Spec:** `docs/voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md` §0/5/6/9/10。全体の残要件は`docs/voice-stack/completion-ledger.md`。

## Global Constraints

- 「既存`SENT` / `CHAT` / `RECEIVED`配信形式は変更しない。」
- 「Windows用依存関係をLinuxで無理にimportしない。」
- 「モデル取得はユーザー同意のうえ、配布元・バージョン・モデルID/ハッシュを記録。」
- 「フォーク独自のビルド成果物へ」`chatbox_yolox_tiny.onnx`を同梱しない。
- Windowsの既存venv選択・Job Object・開発コマンドを維持し、他のPython環境を変更しない。
- Pythonコマンドはuv経由。実機未確認の項目は未確認のまま残す。
- 問題はimozuruで調査し、それでも解決策を得られなければ中断する。

## Review Focus

- Linux sidecarをkillしたときPythonが孤児にならない（Task 1）。
- 引数・日本語stdio・空白入りproject pathを破損しない（Task 1）。
- 未設定の新しい環境でモデルを無断取得しない（Task 2）。
- Linux依存変更でWindows環境のパッケージ選択を変えない（Task 2）。
- 再起動後に設定が復元されても古い発声・ミュート解除を自動実行しない（Task 3）。

### Task 1: 開発sidecarのLinux起動とプロセス寿命

**Files:** Modify `utils/dev_sidecar/src/main.rs`; Create `tests/platform/test_dev_sidecar.py`; Linux起動手順は`docs/voice-stack/local-setup-linux.md`へ。

**Interfaces:** Consumes `VRCT_DEV_VENV`と`src-python/mainloop.py`。Produces Linuxの`.venv/bin/python`選択とUnix `CommandExt::exec()`による同一PIDのstdio実行。Windowsは既存`.venv/.venv_cuda`、Scripts/python.exeとJob Objectを維持。

- [ ] テストを先に追加。rustcで実ラッパーを一時projectへビルドし、実Pythonで日本語stdin/stdout・argv・cwd・PID・exit codeを照合する。子の待機中にラッパーPIDを終了すると同じPythonも終了する。空白pathと不正venv、missing interpreterを含む。
- [ ] `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project python -m pytest -q tests/platform/test_dev_sidecar.py`を実行。Expected: LinuxでScripts/python.exe参照により失敗。
- [ ] OS別interpreter pathとUnix execを最小実装。Windowsのstatus待機は維持。
- [ ] 同コマンド。Expected: 全PASS。既存音声suiteも実行し回帰を確認。
- [ ] 小さなローカルコミットにまとめる。

### Task 2: 本番Python環境とモデル取得の制御

**Files:** `requirements.txt`のOS marker、Linuxセットアップ手順、必要な`src-python/models/transcription/transcription_transcriber.py`のimport境界。起動時モデル取得の制御は`config.py`/`controller.py`と対応UI/APIに最小追加する。

**Interfaces:** 消費するのは固定依存・既存Config/Controller.init。モデルなしでもテキスト/外部TTSを使える本番初期化、モデル取得は明示選択、既存モデルは再利用。

- [ ] 固定requirementsからLinux環境をuvで解決する。Windows限定3依存を外した場合とWindows選択の差分を記録。外部コード・packageの未確認APIは原典で確認する。
- [ ] import/初期化の実失敗を再現するテストと、設定の既定値・永続化・明示download・再起動のテストを先に書く。Expected: 修正前に該当契約でFAIL。
- [ ] 確認できた最小のOS分岐・モデル取得ポリシーを実装。ネットワーク全体を無効化してTTSを動かなくする回避はしない。
- [ ] 実本番Main/Controller.initと選択回帰を実行。Expected: モデル未取得でも初期化完了、取得要求0、既存設定とメッセージ契約維持。
- [ ] 構成・依存版・rawログとローカルコミットを残す。詳細テスト名は実際の初期化障害を同定してからこの節へ追記する。

### Task 3: 実Tauri接続・保存復元・発声受入れ

**Files:** `tools/`のnative起動・受入コマンド、必要なTauri Linux設定、`docs/voice-stack/`の実測記録。

**Interfaces:** Task 1のsidecar、Task 2の本番Python環境、既存UIとSpeechCppTTS・managed route。測定境界をnative IPCと仮想sourceまで通す。

- [ ] Tauri Linux targetをbuildし、本番UIと実sidecarを起動する。Expected: init完了、設定操作に応答。失敗は原典で切り分ける。
- [ ] 新しい設定保存→終了→再起動で設定値と安全なmute状態を確認。通常/停止/OFF/故障復旧の自動試験を追加。
- [ ] 専用PipeWire→実TTSで各1回発声と停止を確認。次にホスト/VRChat経路で許可済みの受入れを実行し、別々の証拠とする。
- [ ] 全回帰・UI build・配布除外検査を実行し、実機未確認と性能母数を記録。
- [ ] 最終reviewとローカルコミット。P1の残条件を更新し、未合格のままP2完了へ繰り上げない。

Task 2/3は環境実測で詳細化する段階計画であり、未確認の依存やUI自動操作契約を固定済みとは扱わない。
