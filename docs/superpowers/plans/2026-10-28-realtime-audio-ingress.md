# Realtime audio ingress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 連続PCMの24kHz変換と有界入力queueを作り、実Realtimeへ流す。
**Architecture:** 短い同期capture push→有界queue→単一async workerで連続resample→既存SpeechCppRealtime.feed。物理captureとUIは次工程。
**Tech Stack:** uv/Python3.11、numpy1.26.4、固定soxr1.1.0（取得前に公式license確認）、既存asyncio。
**Spec:** [入力境界設計](../specs/2026-10-28-realtime-audio-ingress.md)、[上位仕様§5/P3](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)。

## Global Constraints

既存legacy provider/recorderは維持。新規録音なし、承認済みモデルと既存合成fixtureだけで試験。
partialは字幕のみ。モデル自動取得、PR/push/上流連絡なし。未測定の遅延やWindows実機を合格としない。
依存はuvで固定。音声/認識本文をログや共有docsへ保存しない。

## Review Focus

- resamplerが0出力を返す期間やnative残留でPCMが際限なく溜まらない。
- timestamp換算がrate差や分割で将来/新しい時刻を偽装しない。
- stop/overflowとpumpの競合で古いPCMやfinalが残らない。
- stereo downmixの加算overflow、非整数44.1→24k、帯域外alias。
- 未導入依存が既存legacy起動を壊さない。固定wheelのlicenseをwrapperだけで判断しない。

### Task 1: Streaming resampler and bounded ingress

**Files:** Create `src-python/models/transcription/realtime_audio.py`, `tests/voice/test_realtime_audio.py`; Modify `requirements.txt`, `docs/voice-stack/licensing.md`。
**Interfaces:** frozen `CapturedAudio(audio:AudioFrame,captured_ns:int)`; `Pcm24kStream(rate,channels).process(AudioFrame,captured_ns)->tuple[CapturedAudio,...]`, `.close()`;
`RealtimeIngress(rate,channels).push(AudioFrame,captured_ns)->bool`, `.close()`, `await .pump(client)`。
Input5–100ms、queue20items/200ms、250msage。単一worker/consumer。nativependingは200msを超えたらfail。出力最大20ms。

- [x] 公式source/license確認後、依存だけuv導入。モデル不要のRED試験作成: tone/passband/alias、分割一致、timestamp、mono/stereo、zero、format変化、overflow/age/future、停止/取消/二重pump。Expected: module absentFAIL。
- [x] 最小実装、GREEN。Expected: 上記全件PASS、ruff/diffPASS。
- [x] 関連回帰とローカルcommit。Expected: voiceと既存ASRの失敗増なし。

### Task 2: Real server acceptance through ingress

**Files:** Modify `tests/voice/test_speechcpp_realtime_vad_live.py`; Create `docs/voice-stack/realtime-audio-ingress-report.md`。
**Interfaces:** Task1のIngress.pushとpumpを実producerへ接続。入力は元の48kHzfixture、offline比較だけ明示24kHz化。

- [ ] 既存live testを新境界へ接続し、真のnative48kHzを20ms間隔でfeedする。停止後input拒否とclient終了も確認。Expected: actualserver_vad partial/final/無音PASS。
- [ ] related/default失敗集合比較、性能境界とlicenseをreport/ledgerへ。Expected: 新規失敗なし、物理性能と混同しない。ローカルcommit。
- [ ] 一回の独立review、Critical/Importantのみ1回RED→GREEN。Minor保留。全機能作業を継続。

## Pre-flight

Task1→2: 入力timestampはchunk先頭、20msずつ元のrateで供給。serverへ送る時にnowで上書きしない。
Task1→既存Realtime: 各output<=960bytes/20ms、24kmono、最古sampletimestampを渡す。
Task2→capture/UI: 物理captureも同じ境界を使えるが本planの成功は物理capture/字幕UI完成を意味しない。
