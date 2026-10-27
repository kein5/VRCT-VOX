# Native Chatbox併走受入れ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 同じ実Tauri入力からVRChatの本人Chatbox実表示と仮想マイク音声が各1回となることを観測する。

**Architecture:** prepared host route・本人だけのVRChat desktop instanceを使う。実OSC UDPをlocalhostの観測relayで1回だけ転送し、実VRChat画面の固定ASCII識別文字と仮想sourceのPCMを確認する。製品のhandler・IPC・Model・推論は差し替えない。

**Tech Stack:** 既存uv Python、Tauri/WebDriver、PipeWire、speech.cpp/Irodori、既存tesseract eng、spectacle/kdotool。

**Spec:** [実装仕様P1](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)、[先行native測定](../../voice-stack/native-latency-report.md)。

## Global Constraints

- 新規モデル取得なし。OCRは導入済み英語tesseractで識別子だけを検査。日本語全文の認識成功へ読み替えない。
- OSC `/input/Voice`を送らない。game muteを変えず、物理マイクをcaptureしない。
- private instance・本人だけ・試験所有PID/windowを事前確認。ホスト既定入出力/音声service/WiVRnを保持し、変更したVRChat設定と一時routeを復元する。
- 描画検査はDPMS guard下。UDP receiptやTauri DOMをVRChat描画の代用にしない。
- 表示の重複はOSC1件と送信前にない識別子の実描画で確認する。VRChat内部の通知回数を計測したとは言わない。

## Review Focus

- UDP relayが同じdatagramを二重転送しない、bundleも1回（Task1）。
- 想定外OSC addressを転送しない、relay停止時のsocket/threadを解放（Task1）。
- 別window・stale識別子・実音声の重複を成功にしない（Task1）。
- OFF送信でChatboxは更新され音声は出ない（Task1）。
- OCRは文字列位置の証拠のみ、主観音質・遠隔到達・HMD・全OSの完成へ一般化しない（報告）。

### Task 1: 実画面と音声の同時検証

**Files:** Create `tests/platform/native_chatbox.py`, `tests/platform/test_native_chatbox_helpers.py`, `tests/platform/test_native_chatbox.py`; report under `docs/voice-stack/`。

**Interfaces:** `OscForwarder(target)` context owns localhost127.0.0.2 ephemeral UDP socket, `.port`, `.messages`, `.errors`; forwards only packets whose decoded addresses are `/chatbox/input` or `/chatbox/typing`, byte-for-byte once. `marker_visible(ocr_text, marker)` matches one standalone ASCII marker. Test uses existing env for VRChat PID/window/replay sink/speech binary/model; `VRCT_TEST_NATIVE_CHATBOX=1` opt-in.

- [x] Write model-free real UDP tests for byte-preserving single/bundle forwarding, unknown Voice rejection and teardown; marker stale/missing/duplicate rejection. Run Expected RED absent helper.
- [x] Implement helper, run Expected PASS.
- [x] Implement native original/OFF cases with distinct `VRCTCHECKA`/`VRCTCHECKB` appended to fixed Japanese text. Compare independently generated reference PCM twice. Real UI config/send only. Assert source speech1 / OFF silence, UDP1 each, marker absent before/present after in PID/focus-checked VRChat screenshot; manually inspect Japanese text in raw images too.
- [x] Run opt-in host test under existing guard; Expected2 cases pass or explicit failure. No benchmark percentile from2 cases. Preserve screenshots/PCM locally, shared JSON only metadata/results.
- [x] Restore Above Chatbox position, P1 mic input, noise suppressionON, original playback/defaults/mutes; normal quit of owned VRChat, remove owned temporary routes/input daemon, verify unchanged WiVRn/audio services.
- [x] Run related platform/voice regression, Expected no new failures. Commit tests/report and review this narrow acceptance change.

## Preparation evidence

imozuru official originals in `tmp/voice-resume/research/chatbox/`: Show Own Chatbox, Forward/Above, mirror support, OSC input vs debug receipt. Actual host `VRCTPROBE` preview rendered once at screen bottom and existing eng OCR read the exact marker. This setup probe was direct OSC only and is not native/TTS acceptance. Radial Action Menu requires relative movement; bounded movement→observed highlight→click worked after coordinate convergence stopped safely. All host state is in `tmp/voice-resume/chatbox-host/`.

## Limits

This proves one delivered OSC message with actual own-bubble rendering and one source utterance in the same send. Voice replay through VRChat was independently tested earlier; no new claim of same-run remote-player or physical-hearing confirmation. Another unowned GPU process currently uses about7.7GiB; leave it untouched and record contention, do not treat this as a controlled-load benchmark.
