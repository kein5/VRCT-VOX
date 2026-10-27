# 案B・モデル不要検証 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 案Bの制御・OS混合・停止・誤接続を、モデル不要の自動試験と隔離PipeWireで検証する。

**Architecture:** 外部推論の代わりに区別できる合成信号を使い、OSの経路別gateと最終virtual endpointを評価する。実VCや製品の全体mute UIを実装せず、現P1の原文TTS待ちと取消dispatchは回帰試験で必要な修正を確かめる。

**Tech Stack:** Python標準ライブラリ、uv、pytest、PipeWire/WirePlumber CLI。

**Spec:** [承認された検証対象](architecture-evaluation-poc.md)、[ADR 004](adr-004-audio-integration-boundaries.md)。2026-10-27、依頼者がBの検証開始と「まずモデル不要」を選択。実行・記録担当はCodex。最終製品採用は未決定。

## Global Constraints

- ユーザー指定: Pythonはuvを使う。モデル・VC runtimeを新規取得しない。
- 既存TTS取消でVCを止めない。全体muteは明示解除まで保持する。
- 合成信号だけをcaptureし、通常のdefault・実マイク・VRChat経路を変更しない。
- 禁止信号0・旧世代再生0。停止対象の消失目標p95≤100ms/最悪≤250ms、2秒継続確認。
- fake推論、private graph、backend受付時刻を実VC・UI submit・VRChat E2Eと呼ばない。
- Windows実機、実VC、ASR/GPU混在、物理device clockは未検証として残す。

## Review Focus

- Mainに既に並んだchatが取消後に発声しないこと。ただしテキスト配信は続く（Task 1）。
- 遅い翻訳中のTTS設定変更や取消で旧世代が復活しないこと（Task 1）。
- 合成信号のreader停止を無音として誤判定しないこと（Task 2）。
- 全体mute中のproducer再作成や新TTSでgateが勝手に開かないこと（Task 2）。
- endpoint消失時にwriterだけを調べ、consumerのfallbackを見落とさないこと（Task 2/3）。

---

### Task 1: TTSの翻訳待ち・停止待ちを再現して修正

**Files:** Modify `src-python/controller.py`, `src-python/mainloop.py`; tests `tests/voice/test_controller_integration.py`, `tests/voice/test_priority_cancel.py`.

**Interfaces:** 既存`/run/stop_voice`と`/run/send_message_box`を維持。backend受付時にchatのTTS generationをstampし、Controllerは古い世代の音声だけを拒否する。外部JSON応答形式は変更しない。

- [ ] 翻訳がEventで止まっていても原文TTSが先に出力する試験、訳文が待つ試験を書く。
- [ ] Mainの3 workerを占有してもreceiver経由のstopが届く試験と、取消前に受付済みのchatが後から発声しない試験を書く。変更前の失敗を確認する。
- [ ] 原文分岐を翻訳前に移し、訳文分岐は末尾に保持。stopは一般キューの外で取消信号を送る。受付世代を渡し、旧chatの音声を抑止する。
- [ ] `uv run --no-project --with-requirements requirements-voice-test.txt python -m pytest -c tests/voice/pytest.ini tests/voice -q`。Expected: 全PASS。既存70 Controllerケースも維持。
- [ ] 検証済みの変更をcommitする。

### Task 2: OS経路別gate・混合・consumer fallbackのPoC

**Files:** Create `tools/voice_b_poc.py`, `tests/voice/test_b_poc.py`; reuse `tools/voice_acceptance.py` private_graph/loopback helpers. CI lint対象へ新ツールを追加。

**Interfaces:** `ToneObservation.feed(pcm, timestamp_ns)`、`snapshot()`で周波数別のlast-seen/検出数とcapture継続を保持。`main(argv=None)`が新規出力ディレクトリにreport.jsonとtimings.csvを保存。`--runs 30`、`--soak-seconds`で独立graphの反復と任意継続時間を指定する。

- [ ] 手計算可能な440Hz/880Hz/1760Hz信号、無音、odd-byte分割、reader停止での判定を先にテストする。Expected: 未実装でFAIL。
- [ ] private graph内だけにTTS/VC用sink→final sink/sourceを作る。TTS/VC別mute、全体mute、再開、producer終了、endpoint消失時のstrict consumerとdefault consumerを測る。
- [ ] 全体mute中のTTS再作成、TTS取消中のVC継続、別defaultへの禁止信号0を検証。欠測・失敗は報告し、例外でも所有プロセスとノードを解放する。
- [ ] Task 1と同じvoice suiteを実行。Expected: 全PASS。signal decoderの誤検出とdead readerを検出できる。
- [ ] isolated実機smoke後、各30反復と合成信号の継続試験を実行。Expected: 結果を判定どおり報告。性能目標を満たすために測定境界を変えない。
- [ ] 検証済みハーネスと自動テストをcommitする。

### Task 3: 結果・限界・採用条件の更新

**Files:** Create `docs/voice-stack/b-validation-report.md`、`measurements/2026-10-27-b-*.json/.csv`; update ADR 004 and PoC status.

**Interfaces:** Task 1のテスト結果とTask 2の機械可読report。過去値とは別群にする。

- [ ] 版・環境・全試行数・失敗・欠測・p50/p95/p99・reader継続を記録。実VC・UI・VRChat・Windowsは未検証とする。
- [ ] consumer fallback、混合gate、停止時の遅着から、Bで成立した範囲とC再検討条件を更新する。
- [ ] 既存suite、Node契約、lint、diff checkを実行。一般Python suiteは環境依存の失敗も集計し、隠さない。
- [ ] fresh reviewerで変更範囲を確認し、重要指摘を修正・再試験。結果と文書をcommitする。

## 実行範囲の判断

依頼者が既にBのPoCを承認し、モデル不要を指定したため、この計画の再承認待ちは作らず同じworktreeで実行する。使用可能なWindowsやVCモデルがない部分はモデル不要の成功で代用しない。30分の合成継続試験はOS経路の証拠に限定し、仕様の「実VC/ASR/TTS＋VRChat/HMD同時30分」達成とは扱わない。
