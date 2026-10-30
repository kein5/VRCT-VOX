# Managed voice route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 仮想マイクのdaemon所有と明示解除型global muteを実装・検証する。
**Architecture:** PipeWire常駐config＋小さな制御worker。VoiceEventBusのmute latchとOS gateを分け、世代・identityで古い解除を拒否。
**Tech Stack:** Python標準ライブラリ/uv、PipeWire CLI＋小さなC制御helper、既存React/Jotai。
**Spec:** ../specs/2026-10-27-managed-voice-route-design.md

## Global Constraints

- 既存external出力とstop_voiceのTTS単独取消を維持。モデル・pip依存追加なし。Linux制御helperはsystem PipeWire SDKを使う。
- native endpoint起動時mute、明示resumeのみ解除。設定・推論再起動は解除しない。
- pending/unknown/errorを確認済みmuteにしない。physical/default音声を操作せず独立graphで試験。
- Pythonはuv。Windows/実VC/VRChatは未検証と記録。

## Review Focus

- queue・翻訳待ちの古い発話、mute中に受付したchatがresume後に復活しない。
- 遅れたresumeと新mute、endpoint identity変更の競合でbusが開かない。
- failed OS command/missing endpointをmute成功と表示しない。
- managed→external、アプリ再起動でもmute意図を失わない。
- PipeWire restart/WirePlumber state復元でsourceが開かない。停止したreaderを無音としない。

### Task 1: mute latchとmanaged OS制御

**Files:** models/tts/{settings,tts_scheduler}.py、models/audio_routing/{managed_route,pipewire_gate}.py、config/pipewire/90-vrct-managed.conf、tests/voice/test_managed_route.py。
**Interfaces:** VoiceEventBus.set_muted(bool)、VoiceRoute.configure(managed)/mute()/resume()/status()/close()、PipeWireGate.inspect()/set_muted(bool, expected_identity)。statusはmanaged/requested_muted/observed_muted/ready/pending/error。OS操作は制御worker内。

- [x] latchがconfigure/cancelで解除されずpublishを拒否し、明示resume後の新規要求のみ通る試験をRED→GREEN。
- [x] workerの初期mute、設定変更、identity欠落・再生成、command失敗、stale resumeをRED→GREEN。
- [x] daemon configの初期muteと名前指定のadapterを実装。単体suiteと独立graph smokeで検証。Expected: tests pass、native初期mute。
- [x] 検証済み差分をcommit。

### Task 2: Controller/API/UI/CLI統合

**Files:** controller.py、config.py、mainloop.py、src-ui/logics/voice/useVoice.js、useReceiveRoutes.js、VoiceSettings.jsx、locales/en.yml/ja.yml、tools/voice_route.py、tests/voice/test_managed_controller.py。
**Interfaces:** atomic voice_mute_state.json、routing設定、voice_route status/priority mute/resume endpoints。CLI status/mute/resumeは同じbackendを使う。

- [x] 旧payload互換、mute中のchatと翻訳遅着、設定保存で解除されないこと、起動時再mute、優先受付をRED→GREEN。
- [x] backend/APIとUIのrouting選択・mute/resume・pending/失敗表示を接続する。native stateへ触れるのは明示managed選択時だけ。
- [x] uv voice suite、Node契約、Vite、Ruff。Expected: green、既存テキスト契約を保持。
- [ ] 検証済み差分をcommit。

### Task 3: 実経路確認と記録

**Files:** tools/voice_route_acceptance.py、docs/voice-stack/managed-route-report.md、measurements/2026-10-27-managed-*、local-setup-linux.md。
**Interfaces:** 配布configでprivate daemonを起動し、実VoiceRoute＋VoiceEventBusを使う。JSON/CSVへ測定境界・全試行を保存。

- [x] 合成音でengine終了後identity維持、mute保持、制御再起動、daemon再起動初期mute、30回停止＋2秒確認を実行。失敗・欠測はそのまま記録。
- [x] 導入/戻し手順、未検証事項、computer-use不足を記録。host再起動・モデル取得は不要。
- [x] 全体fresh reviewの重要指摘を失敗試験から修正。voice suite/Node/build/lint/diff確認、一般suiteの環境失敗も記録。成果物をcommit。

依頼者は前回提示した手順1の実行を明示したため、既存承認の範囲でinline実行する。GUI操作スキルの不足は手順1の実装を止める理由にしない。
