# Realtime captions integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LinuxのRealtime ASRを本番設定・字幕置換・確定翻訳へ接続し、legacyと切替可能にする。
**Architecture:** source別session ownerがcapture/Ingress/WSを管理。bounded update queueと独立final workerでUI/翻訳を分離し、namespaceを停止時に無効化する。
**Tech Stack:** Python3.11/uv、既存speech.cpp/PipeWire/soxr、React/Jotai、既存Controller/overlay/IPC。
**Spec:** [設計](../specs/2026-10-28-realtime-captions-integration.md)、[要件P3/§3–5](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)。

## Global Constraints

既定OFF・再起動時自動録音なし。新規モデル/録音なし、実試験はprivate synthetic source/sink。
既存SENT/RECEIVED/CHAT形式とlegacy providerを維持。partialはOSC/TTS/clipboard/logger/historyに渡さない。
Realtime speakerのOSC/TTSは禁止。Linux経路変更は停止・再選択、fallbackなし。
stdout/保存ログへPCMを出さない。本文はUI表示に必要な通知と明示logger設定だけ。
Windows/物理ADC/VRChat混在負荷を未測定のまま合格扱いにしない。上流連絡/PR/pushなし。

## Review Focus

- stopより前にqueueへ入ったstart/finalや遅い翻訳戻りが、新しいsessionへ混入しない。
- source別sessionの片方の障害・停止が他方を止めない。
- speakerにlegacy再送設定が有効でも他人の発言をOSC/TTSへ再送しない。
- partial/final/翻訳の順序逆転や旧namespaceで字幕行が増殖・復活しない。
- 設定変更・UI再接続・アプリ終了で古いcaptureや自動録音を残さない。

### Task 1: Session ownership and validated settings

**Files:** Create `src-python/models/transcription/realtime_session.py`, `src-python/models/transcription/realtime_settings.py`, `tests/voice/test_realtime_session.py`, `tests/voice/test_realtime_settings.py`。Modify `capture_pipewire.py` に非joinの`request_stop()`を追加。
**Interfaces:** `SessionOptions(base_url,model,language)`。`RealtimeSession(source,options,endpoint,*,capture_factory,client_factory)`、`start()`はbackground起動、`request_stop()`は同期無効化/非join、`close(timeout=3)->bool`、`pop_update(timeout=.05)->TranscriptUpdate|None`、`health()->dict`、`is_current(namespace)->bool`。
stateはidle/starting/ready/stopping/failed/closed、各instance一度だけ開始。update queue32、満杯なら停止。model metadata preflightは既存REST、期限5s・cancel付き。例外は固定codeのみ。
settingsはversion1/base_url/model/mic{language,endpoint}/speaker{language,endpoint}。endpoint数値はIPCで十進文字列、稼働stateは保存しない。model空/defaultendpoint Noneは保存可、開始時拒否。

- [ ] RED: settings不正URL/unknown field/不正identity、session同時2source/停止中start/partial-final/切断/queue32超過/停止後pop破棄/再利用拒否、初期化取消。Expected: 未実装FAIL。
- [ ] 実装しGREEN。capture callbackはIngress.pushだけ、WS loopは翻訳/表示を呼ばずbounded queueへ渡す。stopはnamespaceとqueueを先に無効化してclient/captureを終了。Expected: 模擬依存でhost入力なし、期限内cleanup。
- [ ] 関連/default検証、ruff/diff、ローカルcommit。Expected: 新規FAILなし（既知16は名前一致を記録）。

### Task 2: Controller/config/IPC and final translation

**Files:** Modify `src-python/config.py`, `src-python/controller.py`, `src-python/mainloop.py`, `src-python/models/message_pipeline.py`; Create `src-python/models/transcription/realtime_delivery.py`, `tests/voice/test_realtime_controls.py`, `tests/voice/test_realtime_delivery.py`。
**Interfaces:** config.REALTIME_ASR_SETTINGS。Controller get/setRealtimeASRSettings、getRealtimeASREndpoints(data{source})、getRealtimeASRModels、getRealtimeASRState、startRealtimeASR(data{source,_realtime_generation})、stopRealtimeASR(data{source})。
IPC `/get/data/realtime_asr_{settings,endpoints,models,state}`, `/set/data/realtime_asr_settings`, `/run/{start,stop}_realtime_asr`。stopはreceiverで先行、start世代はbackend受信時付与。
UI通知 `/run/realtime_caption` にsource/namespace/generation/item_id/revision/state/text/translations。final queue最大4/WS受信時刻から期限2s、重い翻訳後に再検証。受信時刻を`realtime_events.py`/`speechcpp_realtime.py`/`realtime_session.py`で保持し、停止後IPC書込はUIのgenerationでも拒否する。字幕通知とfinal翻訳は別worker。

- [ ] RED: 保存復元OFF、同source legacy排他、2source独立、古いstart/翻訳後stop/overflow、speaker再送設定ONでもOSC/TTS0、partial副作用0。Expected: route/method未実装FAIL。
- [ ] 既存翻訳/formatterを共用し、finalだけ同idの翻訳通知へ接続。legacy呼出しの既定動作を維持。副作用直前にnamespace/期限を検査。設定変更は該当session停止、shutdownで全所有worker終了。Expected: 新旧pipeline回帰PASS。
- [ ] IPC順序/Controller回帰/既存translationテスト、ローカルcommit。Expected: no duplicate final、stop後の未公開結果なし。

### Task 3: Realtime controls, subtitle replacement and overlay

**Files:** Create `src-ui/logics/transcription/useRealtimeASR.js`, `src-ui/logics/transcription/realtimeCaptionState.js`, `src-ui/views/app/config_page/setting_section/setting_box/transcription/RealtimeASRSettings.jsx`, `tests/voice/test_realtime_ui.py`; Modify `src-ui/logics/useReceiveRoutes.js`, `src-ui/logics/common/useMessage.js`, transcription `Transcription.jsx`, `src-python/models/overlay/overlay_image.py`, `src-python/model.py`。
**Interfaces:** `applyRealtimeCaption(current,payload,activeNamespaces)`はsource/namespace/item_idでupsert、revision逆行/terminal後partial/旧namespace拒否。既存legacyappendを変更しない。overlayはoptional caption_id/stateでpending置換・discard、legacy呼出しは既存append。

- [ ] RED: partial→partial→final→translationで1行、逆順/旧namespace拒否、停止でpending削除、legacyappend維持、モデル/言語/端点選択と開始停止。Expected: reducer/component未実装FAIL。
- [ ] 設定/状態/固定errorをUIへ接続し、mic/speaker独立操作。ゲーム専用出力の明示選択、Linuxのみ対応を表示。overlay pendingは履歴に追加せずfinalで1回確定。Expected: UI部品試験とoverlay回帰PASS。
- [ ] frontend build、関連Python/UI回帰、ローカルcommit。Expected: Linux case-sensitive buildPASS、再起動後inactive。

### Task 4: Private full application acceptance

**Files:** Create `tests/platform/test_native_realtime.py`, `docs/voice-stack/realtime-captions-report.md`、results JSON。Modify `docs/voice-stack/completion-ledger.md`。
**Interfaces:** 既存display_power_guardとnative UI harnessを再利用。私有PipeWire既存合成fixture、承認済みspeech.cpp/ReazonSpeech/Silero、実backend/UI。

- [ ] 実backendに繋ぐ受入試験を先に追加。mic/speaker字幕行置換、final翻訳、speaker再送0、停止後更新0、設定復元OFF、legacyへ戻る操作を検証。Expected: 未接続部分はFAILとして修正し、必要な部品のmock合格と区別。
- [ ] 実試験/関連/default回帰、データと未検証事項を記録。Expected: 新規録音なし、物理E2E値を作らない。
- [ ] ローカルcommit後に1回fresh whole-plan review。Important/Criticalだけ1回RED→GREENとsuite、Minor保留。全機能作業を継続する。
