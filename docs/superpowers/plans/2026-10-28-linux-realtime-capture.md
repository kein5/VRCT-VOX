# Linux Realtime capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** identityと元のcycle時刻を保持したLinux OS captureをRealtimeIngressへ接続する。
**Architecture:** libpipewire mainloop helper→bounded timestamped PCM pipe→Python parser/20ms assembler→既存Ingress。推論/UIとcaptureを別に保つ。
**Tech Stack:** system PipeWire1.6.10、C11、Python3.11/uv、既存numpy/soxr/asyncio。
**Spec:** [capture境界設計](../specs/2026-10-28-linux-realtime-capture.md)、[仕様§5/P3](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)。

## Global Constraints

新規録音/モデル取得なし。実試験はprivate graphの合成音源だけ。ホストdefault/device設定を変更しない。
helperはRT_PROCESSを付けない。callbackで待機しない。rawPCMをファイル/ログへ保存しない。
Linux報告時刻を真のADC時刻やWindows合格とは主張しない。PR/push/上流連絡なし。

## Review Focus

- 同名再作成/既定source変更で別音声へfallbackしない。
- 不正packet、部分read、停止中に滞留したPCMを新鮮な時刻で再送しない。
- clock/latency epoch不整合を混ぜない、pw_time.sizeとgraph Qを混同しない。
- capture thread/親終了とpipe backpressureで子/音声が残らない。
- Source/Sink monitorの違いとmanaged route feedbackを誤選択しない。

### Task 1: Native capture and packet decoder

**Files:** Create `native/asr-capture/main.c`, `src-python/models/transcription/capture_packets.py`, `tests/voice/test_capture_packets.py`, `tests/voice/test_asr_capture_native.py`; Modify `tools/build_voice_gate.py`。
**Interfaces:** helper CLI `vrct-asr-capture PARENT_PID OWNER_FD COOKIE SERIAL NAME mic|speaker TAG`。packet `struct '<4sIQQII'`+mono s16le、tagVCA1/rate48000/frames1..960、sequence0から増加。
`CapturePackets.feed(bytes, now_ns)->tuple[CapturedAudio,...]`はrawpacketを20msへ集約、`.close()`はtail破棄。

- [ ] parserRED: 不規則read、seq飛び、巨大長、rate/magic不正、stale/future、20ms再構成、stop。Expected: module absentFAIL。
- [ ] helperRED: missingbinary/build、invalidCLI、wrongcookie/serial、privategraph source/sink packets、endpoint removal、parentdeath/backpressure。Expected: missing native sourceFAIL。
- [ ] helper/parserを実装してGREEN、既存nativehelper回帰。Expected: private合成試験PASS、warning-free build/ruff/diffPASS。ローカルcommit。

### Task 2: Owned Python capture and real ASR

**Files:** Create `src-python/models/transcription/capture_pipewire.py`, `tests/voice/test_capture_pipewire.py`, `tests/voice/test_capture_realtime_live.py`, `docs/voice-stack/linux-realtime-capture-report.md`。
**Interfaces:** `PipeWireCapture(endpoint,source,on_audio,on_error)`, `.start()`, `.stop()`。起動threadがhelperを所有し、callbackはCapturedAudioを既存Ingress.pushへ渡す。開始前にidentity固定、no-default。

- [ ] 生命周期/起動停止/切断/誤endpoint/未読pipe試験RED→GREEN。Expected: zero fallback、期限内cleanup。
- [ ] privategraphの既存合成音声→capture→Ingress→実server_vad。Expected: partial/final、停止後無配信。時刻境界をreportへ。
- [ ] 関連/default回帰とcommit、1回独立review。Important/Criticalだけ1回RED→GREEN、Minor保留。全機能継続。
