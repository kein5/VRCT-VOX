# P1 native送信の計測とOSC併走 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 実Tauriの送信イベントから非無音PCM writeまでを測り、同じ送信のOSCと音声が各1回であることを検証する。

**Architecture:** 既存AudioRouterのfirst-write callbackは時刻を記憶するだけにする。環境変数で明示した場合のみ、ジョブ終了後に本文を含まないJSONLを保存する。試験はDOMイベントを受動観測し、WebDriver往復の前後時刻からブラウザ時計とOS単調時計の対応範囲を求める。OSCは本物のUDP socketで受信する。

**Tech Stack:** Python3.11/uv、既存Tauri/WebDriver、PipeWire、speech.cpp、python-osc。

**Spec:** [実装仕様§6/8](../../voice-stack/spec/codex-implementation-spec.md)、[継続記録](../../voice-stack/completion-ledger.md)。

## Global Constraints

- 既存`SENT` / `CHAT` / `RECEIVED`配信形式は変更しない。
- 新規モデルは取得しない。重い依存を追加しない。既存Irodoriを明示指定した場合のみ実推論する。
- `p50 < 350ms / p95 < 800ms`は温まった短い日本語文のUI送信イベント→仮想マイク向け最初の非無音PCM write。source read / VRChat再生とは分ける。
- GUIはDPMS guard、所有processの終了確認、独立したconfigとPipeWireを使う。
- 未測定や失敗を完了扱いにしない。Windows/HMD/相手への送信は別ゲート。

## 判断と代替

既存last_first_write_msだけではUI/IPC待ちが欠ける。常設の新しい計測IPCやUI表示は今回不要。
syscall traceは音声経路への影響が大きいため採用しない。採るのはopt-inの終了後ログと受動DOM観測。
これは計測手段の選択であり、利用者の連続実装指示に基づく実装者判断。問題が出ればimozuru調査後に再判断する。

## Review Focus

- 診断先が書けない/FIFO/上限超過でも音声・既存送信が停止しない（Task1）。
- ログへ本文・音声・URL・任意例外文字列を出さない。event IDはUUIDのみ（Task1）。
- 無音だけ、write失敗、途中cancelを成功TTFAへ混ぜない（Task1/2）。
- 時計の不整合・広すぎる誤差・標本不足は目標達成と判定しない（Task2）。
- TTS OFFでもOSCを維持し、重複OSCやキュー滞留を性能成功へ混ぜない（Task2）。

### Task 1: opt-in first-write trace

**Files:** Create `src-python/models/tts/voice_trace.py`, `tests/voice/test_voice_trace.py`; modify `src-python/models/tts/tts_scheduler.py`。

**Interfaces:** `write_voice_trace(event_id, started_ns, first_write, outcome)` reads `VRCT_VOICE_TRACE`; `first_write` is `None` or `(monotonic_ns, sample_rate)`; outcome is completed/cancelled/error. JSONL schema1 contains only those metadata fields. Regular file only, maximum8MiB, new file mode0600, errors ignored. OFF emits no trace. First-write capture occurs after sink.write through the existing callback. Logging occurs after playback/stream teardown, outside the condition lock.

- [ ] Write tests: real fake-HTTP→AudioRouter sink with leading silence records the timestamp after first nonzero write exactly once and only after close; disable emits nothing; all-silent/cancel/error retain null start; text privacy; unwritable/oversize/FIFO path leaves worker healthy.
- [ ] Run `UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python python -m pytest -q tests/voice/test_voice_trace.py`; Expected RED missing trace.
- [ ] Implement minimal metadata writer and worker hook; never perform file IO inside first_audio.
- [ ] Run new tests plus `tests/voice`; Expected PASS (host sockets require normal approval scope).
- [ ] Commit code/tests, record exact results.

### Task 2: native UI/OSC/write measurement

**Files:** Create `tests/platform/native_voice_measurement.py`, `tests/platform/test_native_voice_measurement.py`, `tests/platform/test_voice_measurement_math.py`; add report under `docs/voice-stack/`.

**Interfaces:** clock calibration samples `{before_ns, browser_ms, after_ns}`; derive offset interval with declared1ms timer padding, reject disjoint intervals. UI clock mapping yields elapsed lower/upper bounds; each bound uses nearest-rank percentiles. Gate requires>=30 valid warm trials, offset interval width<=5ms, p50 upper<350 and p95 upper<800. Passive capture listener records actual trusted click dispatch `performance.now()`, not WebDriver call start. No handler/IPC/Controller replacement.

- [ ] Math tests first: asymmetric RTT bounds, inconsistent clocks, negative/unordered data, upper-bound percentile, insufficient n. Expected RED missing helpers.
- [ ] Implement clock mapping and summary; run math tests Expected PASS.
- [ ] Add opt-in native test (`VRCT_TEST_NATIVE_MEASUREMENT=1`, real engine via existing env). Use private PipeWire, localhost UDP collector, trace path, actual UI settings/send. Normal and OFF cases compare OSC count and audio; collect>=30 warm real trials for performance run, fixture run exercises contract without performance claims. Every trial waits completion and continuous source silence, preserving failed rows.
- [ ] Run fixture native test under guard; Expected OSC/audio once, OFF OSC once/audio zero, calibrated intervals. Record failure first if existing behavior violates the contract; don't alter thresholds to force green.
- [ ] Run existing Irodori with30 warm sequential trials under guard; Expected measured report, target verdict may pass/fail. Preserve binary/model hashes, versions, boundaries, samples and raw calibration. Do not claim VRChat display from UDP receipt.
- [ ] Run selected native/platform/voice/controller contract regression and relevant Node/build checks only when changed. Expected no new regression; existing16 Windows-only failures stay documented.
- [ ] Commit code/tests/report. Fresh final review for this plan, fix Important/Critical once with RED→GREEN. Subsequent host OSC-display integration is a separate acceptance step with owned VRChat and restored host state.

## Coverage limits

This plan closes the measurement/OSC sender evidence gap. Actual VRChat Chatbox display plus audio remains a host follow-up. VC/ASR/P4/P5 and Windows hardware acceptance are not covered. Clock correlation assumes steady monotonic rates during each short awake trial; before/after consistency and explicit error bounds are required, not synchronization claims.
