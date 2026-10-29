# TTS・RVC独立ページ Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Keep work inline unless delegation is explicitly requested. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** TTSとRVCを別ページで設定し、トップ画面の独立トグルで操作する。TTSは対応モデルへ固定seedとInstructionを送れるようにする。

**Architecture:** 既存Tauri/React/Pythonと音声キューを継続使用する。共通設定レイアウトとCSS変数を再利用し、TTS受付フラグを既存のルートミュートから分離する。サーバー管理・モデル取得同意・直接VCのライフサイクルは維持する。

**Tech Stack:** React、Jotai、SCSS、Tauri、Python3.11、speech.cpp0.9.0。依存追加なし。Python作業はuv。

**Spec:** [設計案](../specs/2026-10-29-tts-settings-ui-design.md)。2026-10-29にユーザーが構成を承認。実装中。モックを製品コードとして取り込まない。

## Global Constraints

- 既存MainPage/SidebarSection/MainSectionの配置・既存スイッチの順序を維持し、TTSとRVCを順に末尾へ追加する。
- トップはTTS・RVC各トグル1行のみ。OFFで再生とキューを止め、下に停止・状態・設定リンクを追加しない。
- 言語設定、右上のクイック設定、ログ/入力欄のリサイズ比率、送信ボタン設定、拡大率・compact modeを維持する。
- モックの非TTS領域は概略。既存部品をモックのHTML/CSSで置換せず、会話欄に大きなTTS帯を追加しない。
- TTSスイッチはchat/mic翻訳の読み上げだけに作用し、原音・直接VC・ASR・翻訳・OSCの設定を変更しない。
- 保存だけでモデル・マイク・発声を開始しない。TTS ONでもルートの安全ミュートを解除しない。
- シードの既定は空文字＝サーバー既定、同梱サーバーではランダム。固定は検証後に整数で送信し、0を保持する。
- Instructionは`instructions`として本文と別送し、未対応時に無言で捨てない。
- 共通経路はデバイス設定へまとめる。直接入力稼働中の変更は止め、OFFを先に求める。
- 新規モデル取得・録音・外部公開・push・上流PRはこの計画の範囲外。
- Windows実機確認は別PCで実施。Linuxの結果をWindows完了と扱わない。

## Review Focus

1. OFF/ON連打と遅延した翻訳・応答でOFF前の音声が復活しないか → Task1/4。
2. ルートのミュート解除・保存・サーバー再起動でTTS OFFが上書きされないか → Task1/4。
3. モデル切替後に古いcapabilityでInstructionを送らないか → Task2/5。
4. 保存失敗・長いパス・UI拡大時にdraftやStopの操作性が失われないか → Task3/6。
5. seed=0/上限/巨大整数/小数、複数言語とmic翻訳で送信値が壊れないか → Task2/5。

## 開始前の整理

- [x] `git status --short`を確認。今回の設計作成前からあるOOM分類の3ファイル差分を保存し、混ぜて完成扱いしない。
  `src-python/models/speech_server/runtime.py`, `tests/voice/test_speech_servers.py`, `tests/voice/test_speech_servers_ui.py`。
  プロセス/Controller試験54件は成功済み。UI案内は未実装で、ブラウザーfixtureの初期ロードtimeoutも未解消。
- [x] 別セッション担当の`docs/security/`、AIT連携ファイル、既存アーキテクチャ資料を変更しない。
- [x] 選択された設計と新しいユーザー指示を照合してから製品実装へ進む。

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

- [x] テスト先行: chat/micの両方をONで受理、OFFで拒否、active+queue取消、原音VCへの呼出しゼロを確認する。
- [x] テスト先行: OFF→ON後のlate final、OFF中のroute unmute、遅いEnableの世代不一致、OFF連打を確認する。
- [x] 失敗を確認してから、受付条件と原子的キャンセルを追加。起動時OFFを提案どおり実装する。
- [x] Enabled変更とsettings変更の双方で古いキュー/確定結果が再生されないことを確認する。
- [x] 原音抑制など既存ポリシーを維持する。OFFにしただけでdirect mute解除もnative gate操作も行わない。
- [x] 応答喪失で成功表示せず、active終了未確認時はstoppingを保持する。
- [x] 関連試験を実行して、制御変更だけをコミットする。

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

- [x] 旧config、seed=0、最大値、負数、小数、指数表記、2^53以上、bool、4000文字境界/改行のテストを追加しREDを確認。
- [x] fake HTTP serverでPOST JSONを観測。指定時の数値seed、独立したinstructions、未指定時の省略を確認。
- [x] 日本語/多言語の分岐とmicの訳文言語、キュー後の設定編集で値が混ざらないことを確認。
- [x] capabilitiesの型・レスポンスサイズ・timeout・model/URL/世代変更を検証する。
  音声callbackでネットワーク照会しない。Instruction/seedを使う時だけ必要な能力を確認する。
- [x] 不明/非対応を区別し、追加指定がない場合の既存の外部HTTP経路を維持する。
  非対応Instructionを空にせず送るときは明確に拒否する。保存値は保持する。
- [x] 本文とInstructionをOSC/翻訳へ混ぜない。ログ/例外にはInstruction本文を追加しない。
- [x] 回帰試験を実行して独立コミット。

## Task 3: TTS・RVCページの分離と既存外観への統一

**Files:**
- `src-ui/views/app/config_page/sidebar_section/SidebarSection.jsx`
- `src-ui/views/app/config_page/setting_section/setting_box/SettingBox.jsx`, `index.js`
- `src-ui/logics/configs/config_page_setter/_aux/useConfigSearch.js`
- 新規`src-ui/views/app/config_page/setting_section/setting_box/tts/Tts.jsx`と`setting_box/rvc/Rvc.jsx`（名称案）
- 既存デバイス設定・文字起こし設定コンポーネント
- 既存`advanced_settings/VoiceSettings.jsx`, `SpeechServers.jsx`, `DirectVoiceSettings.jsx`, `VoiceSettings.module.scss`, `AdvancedSettings.jsx`
- `_templates/Templates.jsx`（必要なら既存wrapperをexport）、`locales/{en,ja,ko,zh-Hans,zh-Hant}.yml`

最初は既存コンポーネントのファイルを大量移動せず、新しいpageが呼ぶ形でもよい。
TTSフォーム/サーバーはTTSへ、RVCフォームはRVCへ、ASR管理は文字起こしへ移す。
原音/Seed-VCは既存の詳細設定に保持する。同じ直接入力制御を別々に起動しない。
共通経路の選択はデバイスへ集約し、各ページは現在値を表示する。TTSの外部出力先はTTSに残す。

- [x] ナビゲーション/検索で「TTS」「RVC」それぞれへ到達し、詳細設定に重複表示しないテストを追加する。
- [x] ページ切替でも入力の完全ID・状態購読・音声を失わないよう、実行時状態を共通hookへ移す。
- [x] 経路変更がdirect stopを伴うことを表示し、稼働中は変更を拒否する。既存全体muteの操作も保持する。
- [x] ローカライズしたラベルと説明、入力、ボタンの区別を既存tokenで実装する。
  新しい外部UIライブラリは追加しない。ネイティブselect/buttonのキーボード操作を維持する。
- [x] 未保存/保存中/保存済み/失敗、破棄、切替前の未保存確認を実装。
  保存APIの応答前に成功と表示しない。global saveで別formまで保存済みにしない。
- [x] 初回/異常時はエンジン準備を隠さず、通常時のみ詳細を折りたたむ。
  detailsを閉じてもイベント購読・サーバー監視・入力操作の寿命を変えない。
- [x] 関連ブラウザー試験とVite buildを通してコミットする。

## Task 4: トップ画面のTTSスイッチ

**Files:** `src-ui/views/app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch.jsx`,
同ディレクトリの既存SCSS（必要な場合のみ）、
`src-ui/logics/voice/useVoice.js`, `src-ui/logics/useReceiveRoutes.js`, locale各言語。
**Test:** 新規`tests/voice/test_tts_controls_ui.py`、既存voice UI entryを使用。

- [x] 既存SwitchContainer/ToggleSwitchの表示を再利用する。TTSというlabelをON/OFFで変更しない。
  role=switch/aria-checked、Space操作、pending、compact表示のnameを検証する。
- [x] 既存4スイッチは並び替えず、TTSを末尾へ1行追加し、その次にTask4bのRVCを置く。下に状態・停止・設定リンクを追加しない。
  MainSection、ログ、入力欄、右上の既存クイック設定を組み替えない。
- [x] 設定ページを一度も開かなくてもstatus/settings/server stateを取得できるよう購読を置く。
  ページ移動でタイマーが重複せず、遅いstateの順序逆転を世代で拒否する。
- [x] 通常ON/OFF、未設定、サーバー停止、管理経路ミュート、ネットワーク断のテストを先に追加。
- [x] トップのOFFで再生中TTSとキューを取り消す。詳細・停止操作は専用設定ページに残し、既存の設定入口を使う。
  切替中は既存スイッチの処理中表示とaria-busy等を使用。失敗時だけ既存通知で理由と設定先を案内する。
- [x] fake IPCでOFFはdisable_ttsだけ、mute_voice/stop_direct_voice/ASR Stopは呼ばれないことを確認。
- [x] 主画面を開いたままの連打/サーバー死活と2つの読み上げソースの競合を検証してコミットする。

## Task 4b: RVC設定と独立トグル

**Files:** Task3のRVCページ、`DirectVoiceSettings.jsx`、`useVoice.js`、`MainFunctionSwitch.jsx`、locale各言語。
**Test:** 既存直接VCのUI/Controller試験と新規RVCトグルのfake IPC試験。

- [x] 既存RVC項目（runtime/model/index/pitch/index_rate）を専用formで編集・保存する。
  同じDirectSettingsのSeed-VC runtime/referenceを消さない。保存は停止中に限定する。
- [x] テスト先行でpitch −24/24・小数・範囲外、index_rate 0/1・NaN・index必須条件を確認。
  バックエンドの現在の検証規則を変えず、入力欄に理由を表示する。
- [x] 入力選択を実行時hookに保持。ページ往復で保持し、再接続で古いIDを採用しない試験を追加する。
- [x] ONはsourceと`mode=converted, engine=rvc`で既存start APIを呼ぶ。
  未設定/未保存/Windows/非managed/他のdirect engine稼働中では開始しない。
- [x] OFFはRVCの既存stop fast pathのみ。準備中もキャンセル可能にする。遅いStartで復活しないことを確認。
- [x] TTS ON/OFF×RVC ON/OFFの4組合せ、ページ移動、接続断、起動失敗をfake IPCで確認。
  RVCの停止でTTS/ASR/OSCが停止せず、TTS OFFでもRVCが継続することを確認する。
- [x] 原音/Seed-VC稼働中にRVCがONに見えたり、勝手にエンジンを入れ替えたりしない試験を追加する。
- [x] 関連試験とVite buildを通してコミット。GUIと実機の検証結果を区別する。

## Task 5: seed/InstructionのGUI

**Files:** Task3のTTSフォーム、`useVoice.js`, 新規または既存のmodel options hook、locale各言語。
**Test:** `tests/voice/test_speech_servers_ui.py`または専用のTTSフォーム試験。

- [x] 日本語/多言語の「ランダム（サーバー既定）／値を指定」、固定整数欄、複数行Instructionを実装。
  0と空欄の差、上限超過、コピー＆ペースト、改行をテストする。
- [x] 対応/非対応/未確認を表示する。Qwen3-TTS0.6Bの非対応時は理由を表示し、既存値を黙って消さない。
- [x] モデル切替で古いcapabilityが採用されないこと、保存した値が再起動で戻ることを確認する。
- [x] モックの例文を製品の既定Instructionにしない。初期値は必ず空欄。
- [x] 同じvoice設定の保存に含め、サーバー再起動なしで次の発話へ適用。モデルロード/録音を誘発しない。
- [x] フォーム試験と送信JSON試験を通してコミットする。

## Task 6: 統合・配布物の確認

**Files:** `tests/platform/native_webdriver.py`の設定遷移ヘルパー、関連native UI試験、
`tests/platform/test_appimage.py`、`docs/voice-stack/`の操作案内と結果記録。

- [x] まずモデル不要でvoice回帰を実行。既存ブラウザーfixtureのpage.goto初期timeoutは原因を切り分け、
  assertionや音声停止期限を緩めて通さない。
- [x] 専用ページへの移動に合わせ、`open_voice_settings`とRVC/ASRへの遷移・設定検索のヘルパーを更新。
- [x] 既存Irodoriでseed=42/同一Instruction/同一CPUの短文n>=2を私有出力へ生成し、PCM一致を検証。
  異なるseedで必ず違うという確率的assertionはしない。Instructionの聴感とCPU/GPU間一致は別項目。
- [x] private PipeWireでTTS OFF後の無音、同時に動作中のdirect音声継続、ASR→訳文→OSC継続を確認。
  OFFクリック→最後のTTS PCM、first audioを計測し、モデル単体時間と分離して記録する。
- [x] DPMSガード下でAppImage通常起動、専用ページ、トップ切替、保存復元、870×654/拡大/長いパスを確認。
  色のコントラスト、tab順、focus、stickyバーによる遮蔽も点検する。
- [x] 同じウィンドウ寸法・拡大率の既存画面と比較し、変更範囲をTTS/RVC追加部分に限定して確認。
  ログ/入力欄比率、言語選択、送信ボタンの表示設定、compact操作を変更前後で照合する。
- [x] Linux build＋AppImage再検査、OCR/モデル非同梱検査を実行。合格するまでインストール済み成果物を置換しない。
- [x] 変更と検証結果をまとめてローカルコミット。Windows/VRChat/聴感など未実施項目を明記する。

## Task 7: ショートカットで小さなチャット入力ウィンドウを開く（追加要望）

ユーザーは既存本体の前面化ではなく、入力欄だけの小さなウィンドウを選択した。
TTS/RVC実装の後に対応する。呼び出しキーを設定可能とし、Yの横取りは既定動作にしない。

**Files:** `src-ui/logics/configs/config_page_setter/hotkeys/useHotkeys.js`、既存チャット送信hook、
`src-tauri/src/lib.rs`、Tauri capability、ミニ入力用Reactビュー・設定locale、対応テスト。

- [x] 既存送信hookとウィンドウ生成/イベント経路を確認し、二重のsidecarを起動しない設計を記録する。
- [x] キーで表示→入力へfocus、Escで閉じる、IME変換中のEnterで誤送信しない試験を先に作る。
- [x] 本体と同じ翻訳・OSC・TTSパイプラインに一度だけ送信する。空入力・長すぎる入力は既存規則を使う。
- [x] 独立ウィンドウの送信イベントは送信元labelと内容を検証する。広いTauri権限を追加しない。
- [x] Windows/X11の既存登録を再利用する。WaylandはGlobalShortcuts portalとactivationの原典を調べ、
  対応状況を検出して登録失敗を表示する。KDEでキー→表示→入力の実機試験を行う。
- [x] 任意キーのVRChatへの抑止・Yオーバーライド、VR空間への入力パネル表示は別機能として扱う。

結果と未確認範囲は `docs/voice-stack/tts-settings-acceptance-2026-10-29.md`、
小窓の設計・portalの判断は `docs/voice-stack/quick-chat-design.md` に記録。
ネイティブWaylandのキー登録自体は未対応。物理IME・Windows・VRChatの実機確認とは区別する。

## 実行コマンドの基本形

```bash
UV_CACHE_DIR=/tmp/vrct-uv-cache uv run --no-project --python .venv_linux/bin/python pytest -c tests/voice/pytest.ini tests/voice/test_scheduler.py tests/voice/test_spoken_scheduler.py tests/voice/test_tts.py -q
npm run vite-build
```

ブラウザーは既存キャッシュのPlaywrightをuvで指定し、`VRCT_TEST_SPEECH_UI=1`と
`VRCT_TEST_CHROMIUM`を設定する。native/私有PipeWire/実モデル試験は既存の明示opt-in条件を使う。
`npm run build`のWindows用wrapperは実行しない。
