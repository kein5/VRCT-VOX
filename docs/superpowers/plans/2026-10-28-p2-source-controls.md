# P2入力選択・開始停止UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** レビュー済みSourceBridgeを本番Controller/UIへつなぎ、明示選択した入力の転送・停止を使えるようにする。
**Architecture:** 既存ControllerにSourceBridgeを1個追加。専用mode coordinatorやPCM daemonを増やさない。選択sourceと開始世代を同じlockで採用し、main receiverの停止は通常queueを迂回。TTS/既存OSC契約は維持。
**Tech Stack:** Python/uv、React/Jotai、既存stdio IPC、Linux PipeWire、Tauri native試験。
**Spec:** [提供仕様P2](../../voice-stack/spec/VRCT_cpp_Codex_Implementation_Spec.md)、[ADR006](../../voice-stack/adr-006-external-source-health.md)、[接続基盤の結果](../../voice-stack/source-bridge-report.md)。

## 設計判断と境界

ユーザーはB・モデル不要の先行検証・全機能まで継続を承認済み。本計画はその入力転送UI部分。
SourceBridgeのconfigure→startを別々にIPC呼出しする案は停止との競合があるため、開始時にselection+generationを原子的に採用する。
別の汎用mode serviceはまだ不要。外部エンジンの状態契約と参照音声は別途調査・確認中。
UIは「選択した入力をそのまま送る」と表示し、実VC確認済みやconverted mode完成とは主張しない。
実エンジンの実装・検証後にVCモードを接続する。新モデル取得・録音・ホストの物理mic captureは行わない。

## Global Constraints

- 既定OFF、source選択だけでは音声を開かない。アプリ再起動で自動再開しない。
- sourceのcookie/serialをUIで保持。serialはJS精度を失わない十進文字列。refreshで同名別serialへ黙って選択を移さない。
- managed routingのみ開始可。全体muteは既存final gate、TTS stopはTTSだけ、入力stopはSourceBridgeだけ。
- 主音声設定でmanaged→externalに切り替える場合は入力も停止。TTS言語/原文訳文設定だけでは入力を止めない。
- stop受信後にqueueに残った古いstartを実行しない。停止handlerはjoin/graph queryを行わない。
- Windowsは列挙/startをunsupportedと明示し、importとTTSの既存経路を維持する。
- UI/IPCに未知のengine-ready情報を捏造しない。実VC・Windows・P2全体は未完。

## Review Focus

- enumerateでsourceの重複/class/managed feedbackを除外し、開始時にidentityを再検証する。
- 非同期の古いstart/状態応答がstop後の音声やUIを再開しない。
- TTS停止、入力停止、全体muteと設定切替の責務・世代が混同されない。
- 再起動で入力転送が自動再開しない。既存stdio/OSC/WebSocket/historyとOFF時の挙動を維持する。
- UIが入力転送を「VC成功」や「全体mute解除」と誤って表示しない。

### Task 1: 選択identityと原子的な開始

**Files:** Modify `src-python/models/audio_routing/source_bridge.py`, `tests/voice/test_source_bridge.py`; Create `tests/voice/test_source_selection.py`。
**Interfaces:** `enumerate_sources()->list[{id:{cookie:str,serial:str,name:str,media_class:str},label:str}]`。`parse_source(value)->Endpoint`はexact keys/ranges/stringsを検査。
`SourceBridge.start(*, source:Endpoint|None=None, expected_generation:int|None=None)`追加。lock内で世代を照合、既存runがactive/stoppingなら別入力への開始を拒否、停止済みならsourceを採用し新runを作る。従来configure/start呼出し維持。
healthに`source`（上述のid形式かNone）と単調`observation_id`文字列を同lockで追加。

- [x] RED: duplicate/feedback/誤class/欠落・不正payload、64bitserial roundtrip、列挙失敗、Windows、stop前世代の開始拒否、停止とselection採用の競合、active中別source拒否、観測順序を試験。
- [x] 実装、GREEN、既存SourceBridge/native関連、Ruff/diffチェック。`feat(audio): bind explicit source selection to start intent`としてcommit。

### Task 2: Controller・stdio・設定画面

**Files:** Modify `src-python/controller.py`, `src-python/mainloop.py`, `src-ui/logics/voice/useVoice.js`, `src-ui/logics/useReceiveRoutes.js`, `src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/VoiceSettings.jsx`, 該当locale。Create `DirectVoiceSettings.jsx`（同じ設定ディレクトリ）と適切なtests。
**Interfaces:** `/get/data/direct_voice_sources`, `/get/data/direct_voice_state`, `/run/start_direct_voice` (`source` payload), `/run/stop_direct_voice`。
receiverがstartにbackend-owned `_direct_generation`を付け、stopを通常queueから分離。Controllerはmanaged確認とTTS routing変更を既存_voice_settings_lockで整合。SourceBridge新APIでgeneration+sourceを原子的に採用。閉じる際は直接入力を停止し、既存全体gate閉鎖とworker回収を行う。
新UI状態は既存routeと独立、observation_idで古いresponseを破棄。dropdownは全identityでkey化、保存/自動開始なし。入力start/stopと全体muteの区別、接続状態/未対応/errorを表示。未実装VCモードを有効な選択肢にしない。

- [x] RED: queuedstart→stop→latehandler、start途中のmanaged解除、TTS設定のみの継続、入力stopとTTSstopの独立、再起動OFF、マッピング/エラー応答、Windows拒否。Reactで古い状態、再列挙の同名置換、明示操作のみを確認。
- [x] 実装、GREEN、Node/UIテスト・Vite build、関連回帰。`feat(ui): control selected input forwarding explicitly`としてcommit。

### Task 3: 本番UIから私有音声経路まで

**Files:** Create platform native input-control test/report、必要な既存native fixture拡張。
**Interfaces:** opt-in実Tauri＋実Controller、DPMSガード、私有PipeWire合成440/880/禁止1760のみ。入力選択→start→stop、TTSとの併用/独立停止、全体mute/解除、設定経路変更、アプリ終了/再起動OFFを確認。

- [x] REDで必要な観測/不良capture拒否を確認後、native実行。端末の物理mic・VRChat・実VCは含めない。
- [x] 自動試験/測定全件、未測定、許諾差分を報告。関連と全体suite（既知16失敗を区別）を実行しcommit。
- [x] 一回の独立review、重要指摘だけRED→GREENの一修正pass。minor保留、継続ledger保持。push/上流連絡/PRなし。

## Pre-flight

Task1のsource payloadとhealth observation_idをTask2のIPC/UIがそのまま使用する。
Task2のreceiver stampはSourceBridge generation、停止は同じSourceBridge.stopなので検証境界が一致する。
Task3のmaster gate/TTS/source停止は独立信号で観測する。実VCの状態契約が未確定でもこの計画は依存しない。
