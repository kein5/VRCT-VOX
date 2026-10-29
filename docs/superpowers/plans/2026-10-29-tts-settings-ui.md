# 音声・TTS専用ページ Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Keep work inline unless delegation is explicitly requested. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TTSを専用ページで設定し、トップ画面から独立してON/OFFでき、対応モデルへ固定seedとInstructionを送れるようにする。

**Architecture:** 既存Tauri/React/Pythonと音声キューを継続使用する。共通設定レイアウトとCSS変数を再利用し、TTS受付フラグを既存のルートミュートから分離する。サーバー管理・モデル取得同意・直接VCのライフサイクルは維持する。

**Tech Stack:** React、Jotai、SCSS、Tauri、Python3.11、speech.cpp0.9.0。依存追加なし。Python作業はuv。

**Spec:** [設計案](../specs/2026-10-29-tts-settings-ui-design.md)。本計画はレビュー用の未着手案。モックを製品コードとして取り込まない。

## Global Constraints

- 既存MainPage/SidebarSection/MainSectionの配置・既存スイッチの順序を維持し、TTSを末尾へ追加する。
- 言語設定、右上のクイック設定、ログ/入力欄のリサイズ比率、送信ボタン設定、拡大率・compact modeを維持する。
- モックの非TTS領域は概略。既存部品をモックのHTML/CSSで置換せず、会話欄に大きなTTS帯を追加しない。
- TTSスイッチはchat/mic翻訳の読み上げだけに作用し、原音・直接VC・ASR・翻訳・OSCの設定を変更しない。
- 保存だけでモデル・マイク・発声を開始しない。TTS ONでもルートの安全ミュートを解除しない。
- シードの既定は空文字＝サーバー既定、同梱サーバーではランダム。固定は検証後に整数で送信し、0を保持する。
- Instructionは`instructions`として本文と別送し、未対応時に無言で捨てない。
- 新規モデル取得・録音・外部公開・push・上流PRはこの計画の範囲外。
- Windows実機確認は別PCで実施。Linuxの結果をWindows完了と扱わない。

## Review Focus

1. OFF/ON連打と遅延した翻訳・応答でOFF前の音声が復活しないか → Task1/4。
2. ルートのミュート解除・保存・サーバー再起動でTTS OFFが上書きされないか → Task1/4。
3. モデル切替後に古いcapabilityでInstructionを送らないか → Task2/5。
4. 保存失敗・長いパス・UI拡大時にdraftやStopの操作性が失われないか → Task3/6。
5. seed=0/上限/巨大整数/小数、複数言語とmic翻訳で送信値が壊れないか → Task2/5。

## 開始前の整理

- [ ] `git status --short`を確認。今回の設計作成前からあるOOM分類の3ファイル差分を保存し、混ぜて完成扱いしない。
  `src-python/models/speech_server/runtime.py`, `tests/voice/test_speech_servers.py`, `tests/voice/test_speech_servers_ui.py`。
  プロセス/Controller試験54件は成功済み。UI案内は未実装で、ブラウザーfixtureの初期ロードtimeoutも未解消。
- [ ] 別セッション担当の`docs/security/`、AIT連携ファイル、既存アーキテクチャ資料を変更しない。
- [ ] 選択された設計と新しいユーザー指示を照合してから製品実装へ進む。

## Task 1: TTS専用の受付制御

**Files:** `src-python/models/tts/tts_scheduler.py`, `src-python/controller.py`, `src-python/mainloop.py`。
**Test:** `tests/voice/test_scheduler.py`, `test_spoken_scheduler.py`, `test_managed_route.py`、新規`test_tts_toggle.py`。

**Interfaces（提案）:**
- `VoiceEventBus.set_enabled(enabled: bool, expected_generation: int | None = None)`。
  `_tts_enabled`と単調増加`_tts_generation`をCondition内で管理する。
- `status()`は既存フィールドを維持し、`tts_enabled`, `tts_generation`, `tts_stopping`を追加する。
- `/run/enable_tts`は`{generation: int}`を受け、世代・保存済みモード・必要なサーバー/出力の準備を照合する。
- `/run/disable_tts`は新しいONを無効化できるよう、すでにOFFでも世代を進める。Stop同様fast pathで処理する。
- `/run/stop_voice`の既存契約は維持。`_muted`/ルートミュートとは別の判定にする。

- [ ] テスト先行: chat/micの両方をONで受理、OFFで拒否、active+queue取消、原音VCへの呼出しゼロを確認する。
- [ ] テスト先行: OFF→ON後のlate final、OFF中のroute unmute、遅いEnableの世代不一致、OFF連打を確認する。
- [ ] 失敗を確認してから、受付条件と原子的キャンセルを追加。起動時OFFを提案どおり実装する。
- [ ] Enabled変更とsettings変更の双方で古いキュー/確定結果が再生されないことを確認する。
- [ ] 原音抑制など既存ポリシーを維持する。OFFにしただけでdirect mute解除もnative gate操作も行わない。
- [ ] 応答喪失で成功表示せず、active終了未確認時はstoppingを保持する。
- [ ] 関連試験を実行して、制御変更だけをコミットする。

## Task 2: モデル能力とseed/Instructionの保存・送信

**Files:** `src-python/models/tts/settings.py`, `speechcpp_tts.py`, `tts_scheduler.py`, `src-python/controller.py`, `mainloop.py`。
必要なら小さな`src-python/models/tts/model_options.py`へ能力レスポンスの検証だけを分離。
**Test:** `tests/voice/test_tts.py`, `test_scheduler.py`, `test_spoken_scheduler.py`、新規`test_tts_model_options.py`。

**Interfaces（提案）:**
- VoiceSettingsに`japanese_seed`, `multilingual_seed`, `japanese_instructions`, `multilingual_instructions`を追加。
  すべてstring、初期値`""`。旧configからの復元は従来の基本POSTと同じになる。
- `VoiceSettings.options_for(language)`は検証済みの`{seed?: int, instructions?: str}`を返す。
  `request_for()`の既存4要素戻り値は維持し、キューに保存した同じsettingsスナップショットを使う。
- `SpeechCppTTS.synthesize_stream(..., *, seed=None, instructions="")`で追加引数を受ける。
- `/get/data/tts_model_options`: role/server/configured_url/server_generationと、上限付きのoptionsを返す。
  認識用ASRモデルAPIは流用しない。サーバー変更後の古い結果を採用しない。

- [ ] 旧config、seed=0、最大値、負数、小数、指数表記、2^53以上、bool、4000文字境界/改行のテストを追加しREDを確認。
- [ ] fake HTTP serverでPOST JSONを観測。指定時の数値seed、独立したinstructions、未指定時の省略を確認。
- [ ] 日本語/多言語の分岐とmicの訳文言語、キュー後の設定編集で値が混ざらないことを確認。
- [ ] capabilitiesの型・レスポンスサイズ・timeout・model/URL/世代変更を検証する。
  音声callbackでネットワーク照会しない。Instruction/seedを使う時だけ必要な能力を確認する。
- [ ] 不明/非対応を区別し、追加指定がない場合の既存の外部HTTP経路を維持する。
  非対応Instructionを空にせず送るときは明確に拒否する。保存値は保持する。
- [ ] 本文とInstructionをOSC/翻訳へ混ぜない。ログ/例外にはInstruction本文を追加しない。
- [ ] 回帰試験を実行して独立コミット。

## Task 3: 音声・TTS専用ページと既存外観への統一

**Files:**
- `src-ui/views/app/config_page/sidebar_section/SidebarSection.jsx`
- `src-ui/views/app/config_page/setting_section/setting_box/SettingBox.jsx`, `index.js`
- `src-ui/logics/configs/config_page_setter/_aux/useConfigSearch.js`
- 新規`src-ui/views/app/config_page/setting_section/setting_box/voice/Voice.jsx`
- 既存`advanced_settings/VoiceSettings.jsx`, `SpeechServers.jsx`, `DirectVoiceSettings.jsx`, `VoiceSettings.module.scss`, `AdvancedSettings.jsx`
- `_templates/Templates.jsx`（必要なら既存wrapperをexport）、`locales/{en,ja,ko,zh-Hans,zh-Hant}.yml`

最初は既存コンポーネントのファイルを大量移動せず、新しいpageが呼ぶ形でもよい。
直接VCとASR管理は独立した見出しで残す。既存AdvancedSettingsからはTTS表示を外す。

- [ ] ナビゲーション/検索で「音声・TTS」へ到達し、詳細設定に重複表示しないテストを追加する。
- [ ] ローカライズしたラベルと説明、入力、ボタンの区別を既存tokenで実装する。
  新しい外部UIライブラリは追加しない。ネイティブselect/buttonのキーボード操作を維持する。
- [ ] 未保存/保存中/保存済み/失敗、破棄、切替前の未保存確認を実装。
  保存APIの応答前に成功と表示しない。global saveで別formまで保存済みにしない。
- [ ] 初回/異常時はエンジン準備を隠さず、通常時のみ詳細を折りたたむ。
  detailsを閉じてもイベント購読・サーバー監視・入力操作の寿命を変えない。
- [ ] 関連ブラウザー試験とVite buildを通してコミットする。

## Task 4: トップ画面のスイッチと状態表示

**Files:** `src-ui/views/app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch.jsx`,
必要なら同じディレクトリへ小さな`TTSControls.jsx`とSCSS、
`src-ui/logics/voice/useVoice.js`, `src-ui/logics/useReceiveRoutes.js`, locale各言語。
**Test:** 新規`tests/voice/test_tts_controls_ui.py`、既存voice UI entryを使用。

- [ ] 既存SwitchContainer/ToggleSwitchの表示を再利用する。TTSというlabelをON/OFFで変更しない。
  role=switch/aria-checked、Space操作、pending、compact表示のnameを検証する。
- [ ] 既存4スイッチは並び替えず、TTSを末尾へ追加。状態・停止・設定リンクはTTS行の近くに収める。
  MainSection、ログ、入力欄、右上の既存クイック設定を組み替えない。
- [ ] 設定ページを一度も開かなくてもstatus/settings/server stateを取得できるよう購読を置く。
  ページ移動でタイマーが重複せず、遅いstateの順序逆転を世代で拒否する。
- [ ] 通常ON/OFF、未設定、サーバー停止、管理経路ミュート、ネットワーク断のテストを先に追加。
- [ ] ON/OFFと「現在の音声を停止」を区別して表示し、専用設定に直接遷移できるようにする。
- [ ] fake IPCでOFFはdisable_ttsだけ、mute_voice/stop_direct_voice/ASR Stopは呼ばれないことを確認。
- [ ] 主画面を開いたままの連打/サーバー死活と2つの読み上げソースの競合を検証してコミットする。

## Task 5: seed/InstructionのGUI

**Files:** Task3のTTSフォーム、`useVoice.js`, 新規または既存のmodel options hook、locale各言語。
**Test:** `tests/voice/test_speech_servers_ui.py`または専用のTTSフォーム試験。

- [ ] 日本語/多言語の「ランダム（サーバー既定）／値を指定」、固定整数欄、複数行Instructionを実装。
  0と空欄の差、上限超過、コピー＆ペースト、改行をテストする。
- [ ] 対応/非対応/未確認を表示する。Qwen3-TTS0.6Bの非対応時は理由を表示し、既存値を黙って消さない。
- [ ] モデル切替で古いcapabilityが採用されないこと、保存した値が再起動で戻ることを確認する。
- [ ] モックの例文を製品の既定Instructionにしない。初期値は必ず空欄。
- [ ] 同じvoice設定の保存に含め、サーバー再起動なしで次の発話へ適用。モデルロード/録音を誘発しない。
- [ ] フォーム試験と送信JSON試験を通してコミットする。

## Task 6: 統合・配布物の確認

**Files:** `tests/platform/native_webdriver.py`の設定遷移ヘルパー、関連native UI試験、
`tests/platform/test_appimage.py`、`docs/voice-stack/`の操作案内と結果記録。

- [ ] まずモデル不要でvoice回帰を実行。既存ブラウザーfixtureのpage.goto初期timeoutは原因を切り分け、
  assertionや音声停止期限を緩めて通さない。
- [ ] 専用ページへの移動に合わせ、`open_voice_settings`と設定検索のヘルパーを更新。
- [ ] 既存Irodoriでseed=42/同一Instruction/同一CPUの短文n>=2を私有出力へ生成し、PCM一致を検証。
  異なるseedで必ず違うという確率的assertionはしない。Instructionの聴感とCPU/GPU間一致は別項目。
- [ ] private PipeWireでTTS OFF後の無音、同時に動作中のdirect音声継続、ASR→訳文→OSC継続を確認。
  OFFクリック→最後のTTS PCM、first audioを計測し、モデル単体時間と分離して記録する。
- [ ] DPMSガード下でAppImage通常起動、専用ページ、トップ切替、保存復元、870×654/拡大/長いパスを確認。
  色のコントラスト、tab順、focus、stickyバーによる遮蔽も点検する。
- [ ] 同じウィンドウ寸法・拡大率の既存画面と比較し、変更範囲をTTS追加部分に限定して確認。
  ログ/入力欄比率、言語選択、送信ボタンの表示設定、compact操作を変更前後で照合する。
- [ ] Linux build＋AppImage再検査、OCR/モデル非同梱検査を実行。合格するまでインストール済み成果物を置換しない。
- [ ] 変更と検証結果をまとめてローカルコミット。Windows/VRChat/聴感など未実施項目を明記する。

## 実行コマンドの基本形

```bash
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python pytest -c tests/voice/pytest.ini tests/voice/test_scheduler.py tests/voice/test_spoken_scheduler.py tests/voice/test_tts.py -q
npm run vite-build
```

ブラウザーは既存キャッシュのPlaywrightをuvで指定し、`VRCT_TEST_SPEECH_UI=1`と
`VRCT_TEST_CHROMIUM`を設定する。native/私有PipeWire/実モデル試験は既存の明示opt-in条件を使う。
`npm run build`のWindows用wrapperは実行しない。
