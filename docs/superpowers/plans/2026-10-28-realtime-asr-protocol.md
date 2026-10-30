# Realtime ASR protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** speech.cpp Realtimeの暫定/確定イベントを分離し、有界・停止可能なローカルWSセッションを検証する。
**Architecture:** 既存batch transcriberとは別の小さなイベントreducerとasyncio WS producer。mic/speakerは別instance・session namespace。capture/UI/翻訳への接続は次段。モデル同意に依存しない模擬試験と、既存モデルのmanual-commit試験を先に行う。
**Tech Stack:** uv/Python3.11、既存websockets15.0.1、AudioFrame、標準asyncio。依存追加なし。
**Spec:** [仕様§3/§5/P3](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)、[固定speech.cpp0.9.0仕様](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/docs/server.md#realtime-transcription)。

## Scope / decisions

- ユーザーの閉ループ実装指示を継続。Silero取得は後にユーザー承認され、固定artifact/hashを検証済み。未承認モデル・新規録音なし。
- 24kHz mono s16leのみをfeedで受け付け、違うrate/channelsを再解釈しない。capture/resamplerは次段。
- 生音声や認識本文をログへ出さない。local_url規則、proxy/redirect拒否。
- 自動再接続や古いPCMの再送はしない。切断後は新instanceと新namespaceで明示start。
- `server_vad`を通常設定、manual commitは既存モデルによるプロトコル検証用。VAD未導入時の実試験合格をserver_vadの合格と数えない。
- partialは字幕更新だけ。completedの全文へ置換し、completeだけを一度finalとして出す。下流OSC/TTSはこの段階で呼ばない。
- reducerは単一event loop専用。pending最大8、各text4000文字、terminal記録256件。未知itemのcompleted/deltaは捨てる。
- producerはfeed直列・有界出力queue32。feed中の別feed、古いframe（250ms超）、出力queueあふれはsessionを閉じる。内部PCM queueは作らない。capture側の有界queueは次段。

## Review Focus

- 同一completed再送やfinal後のdeltaで、二重final/確定字幕の巻戻りが起きない。
- clear/停止/切断後に遅れて来るfinalを復活させない。
- micとspeakerで同じitem_idでもnamespaceが衝突しない。
- サーバ無応答・巨大event・低速consumer・旧frameを無制限に溜めない。
- 意図しないredirect/proxy、別rateのPCM、session.update未承認状態で音声を送らない。

### Task 1: Transcript event reducer

**Files:** Create `src-python/models/transcription/realtime_events.py`, `tests/voice/test_realtime_events.py`。
**Interfaces:** `TranscriptEvents(source, namespace)`; `accept(event:dict)->tuple[TranscriptUpdate,...]`; `begin_clear()`, `close()`。
`TranscriptUpdate` frozen fields source/namespace/item_id/revision/text/is_final/state (`partial|final|discarded`)。
speech_started/committedでitemを登録、deltaを追加、completedで全文置換、failed/model_limitでdiscarded。clear中はackまで新旧すべての結果を抑止し、ack後も未知item結果を捨てる。

- [x] RED: partial置換・event_id/完成item重複・final後delta・failed/model_limit・clear中とack後のlate final・閉鎖・2source同一ID・pending/text上限・未知item・古いterminal記録の再送。Expected: 新moduleなしFAIL。
- [x] 最小reducer実装しGREEN。既存イベント形式は変更しない。Expected: unit PASS、Ruff/diff PASS。
- [x] 関連suiteを実行しcommit。Expected: 新規失敗なし。

### Task 2: Local WS producer and protocol acceptance

**Files:** Create `src-python/models/transcription/speechcpp_realtime.py`, `tests/voice/test_speechcpp_realtime.py`, `tests/voice/test_speechcpp_realtime_live.py`; report `docs/voice-stack/realtime-asr-protocol-report.md`。
**Interfaces:** `SpeechCppRealtime(base_url, model, language, source, server_vad=True)` async `start()`, `feed(AudioFrame,captured_ns)`, `commit()` (manual only), `clear()`, `stop()`; async `next_update()` returns Task1 updates. status exposes fixed safe codes only. connect/config deadline2s, send1s, close.5s; incomplete pending item15s deadline. One loop/one producer per instance.

- [x] RED: real mockWS created→update→updated contract、exact24000 mono append、2sources隔離、final1回、clear ack/late final、切断/再start別namespace、wrong config/error、接続待ちcancel、server無応答、巨大JSON、slowconsumer/oldframe/同時feed、redirect/proxy拒否。Expected: producer absentFAIL。
- [x] producer実装、GREEN。Expected: allmock casesPASS、Ruff/diffPASS。reader停止時は未配信結果破棄、stopはsocket/task解放。
- [x] 既存ReazonSpeechサーバでmanual commit/file-input試験。Silero承認があれば別固定artifact/hash検証後server_vadも測定、なければ未検証。Expected: manual completedは1回、mic/speakerは別namespace、rawprivate保存。回帰比較とcommit。
- [x] 一回の独立review、Important/CriticalだけRED→GREEN一修正pass。Minor保留。全機能作業継続、PR/pushなし。

## Pre-flight

Task1→2: reducerはsocket/モデルに依存せず、一event loopだけで状態更新。producerがclear開始時にbegin_clearを呼ぶ。
Task2→後続capture: feedはtimestamp/rate/channelsを検査し、captureのformat変換とqueue制限を代行したと主張しない。
Task2→後続UI: partial/final/discardedを別eventとして渡す。legacy SENT/CHAT/RECEIVEDは変更しない。
