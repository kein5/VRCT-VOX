# speech.cpp専用REST ASR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 導入済み認識モデルを使い、既存APIの未対応引数を送らないspeech.cpp専用REST接続を自動検証する。
**Architecture:** 外部speech.cppサーバへlocalhost限定HTTP。既存Whisper/OpenAI providerは変更しない。REST部品とファイル入力CLIを先に検証し、Realtime/capture/UI/final発火は次の独立計画へ。
**Tech Stack:** uv/Python3.11、標準HTTP/WAV、既存AudioFrame/CancelToken、speech.cpp0.9.0と既存ReazonSpeech GGUF。
**Spec:** [仕様§5 ASR/P3](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)、[公式REST契約](https://github.com/nyosegawa/speech.cpp/blob/main/docs/server.md)。

## Context / constraints

ユーザーは全機能まで閉ループ実行を指示済み。P2の主観品質回答を待つ間、独立したP3の先頭工程を進める判断。
新規モデル取得・マイク録音なし。既存合成入力と導入済みReazonSpeechだけを使用。
2026-10-28の隔離REST probeはHTTP200、モデルid `reazonspeech-nemo-v2`。これは製品統合成功ではない。
OpenAI互換provider流用はtemperature/verbose_jsonのconfidence前提が合わず不採用。直接HTTP専用adapterを選ぶ。
汎用provider抽象化の改修は不要。モデルのtask/languages/optionsを`/v1/models`で検査する。
URLは既存local_url規則、redirect/proxy不使用。音声/書き起こし/サーバ本文をエラーログへ出さない。
全体timeout/cancelはpreflightから応答body完了まで。partial/model_limitをfinalとして返さない。
同時要求の直列化・認識精度・physical latency・WSはこのREST工程の合格と別。

## Review Focus

- 選択モデルがsynthesisへ差し替わった時、音声を送らず失敗する（Task1 model/task test）。
- redirect/環境proxy/資格情報付きURLで外部へ音声を送らない（Task1 local URL/redirect test）。
- 応答が1byteずつ来る/headersで停止する時、timeoutとcancelで終わる（Task1 transport tests）。
- model_limit/不正JSON/巨大応答を確定文字列として使わない（Task1 negative tests）。
- stereo/異rateのPCMを誤ったWAV headerへ詰め替えない（Task1 real multipart/WAV assertions）。

### Task 1: 専用REST部品・CLI・実サーバ検証

**Files:** Create `src-python/models/transcription/speechcpp_asr.py`, `tools/speechcpp_asr_poc.py`, `tests/voice/test_speechcpp_asr.py`; Create report `docs/voice-stack/speechcpp-rest-asr-report.md`。
**Interfaces:** `SpeechCppASR(base_url, timeout=15.0).recognizers(cancel_token=None)` returns validated recognition model metadata. `transcribe(audio:AudioFrame, model:str, language='auto', cancel_token=None)` returns immutable `ASRResult(text, model, requested_language)` only on complete response. `ASRError` carries safe code, no raw server body. PCM max60s, response max1MiB. CLI takes explicit WAV/url/model/output paths; report contains hash/duration/text length/timing, not transcript. No model launch/download from adapter.

- [x] RED: local URL refusal, recognition model discovery, missing/wrong task/language, exact multipart params, stereo WAV/rate preservation, success/empty text, model_limit, redirect, bad/large JSON, error privacy, header/body stall cancellation and absolute timeout. Expected: module absent failures.
- [x] Implement minimal HTTP adapter with bounded reads, total deadline and interruptible socket; CLI preserves PCM format and refuses overwrite. Expected: same cases PASS, Ruff/diff PASS.
- [x] Real installed server + synthetic WAV in isolated loopback: metadata and actual transcript success; unsupported language/model rejected before audio upload. Unit+related regressions and existing16 failures compared. Expected: no new regression; no new models or host audio changes. Commit deliverable/report.
- [ ] One independent final review. Important/Critical only one RED→GREEN pass; minors ledger. Continue full user goal, retain workspace/evidence, no push/PR.

## Pre-flight / scope

One task; no shared task interfaces. Reuse existing AudioFrame (s16le with explicit channels/rate) and CancelToken cancellation contract; do not change their behavior.
This plan covers only P3 REST-first requirement. Existing transcriber/config/UI/OSC semantics stay unchanged until subsequent Realtime integration.
