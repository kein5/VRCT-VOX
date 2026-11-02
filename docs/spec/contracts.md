# 契約

変えてはいけない約束と、それを確かめているテスト。新しい機能や変更は、ここにある契約を破らないようにする。契約を変えるときは、理由と移行の手順を決めてからこの表を直す。

根拠の欄の`AGENTS.md`と`PRODUCT.md`は、ユーザーと合意した方針である。テストの欄が「手動」の契約は、変更のたびにレビューか実機の確認で守る。

## 互換性

| ID | 契約 | 根拠 | 確かめているもの |
|---|---|---|---|
| CT-01 | IPCのメッセージの形（`endpoint`と`data`の要求、`status`と`endpoint`と`result`の応答）と状態コードの意味を変えない | `AGENTS.md`「互換性」 | `tests/voice/test_priority_cancel.py`（受付と再試行）、`tests/voice/test_headless_and_ui_contract.py`（音声のエンドポイントが両側にある） |
| CT-02 | サイドカーが送る通知の名前はすべて`run_mapping`に定義する | 送る時点の例外を防ぐ | `src-python/test/test_controller_run_mapping_contract.py` |
| CT-03 | 既存のエンドポイント名、設定キー、OSCのアドレス、内部の識別子`VRCT`は、名前を変えるという理由だけで置き換えない。保存先やアプリIDを変えるときは移行の処理を用意する | `AGENTS.md`「互換性」、`docs/voice-stack/project-rename.md` | `tests/voice/test_fork_distribution_identity.py`、`tests/voice/test_config_and_distribution.py` |
| CT-04 | `config.json`は壊れた値や知らないキーがあっても起動できる。無効な値は保存しない | `src-python/config.py` | `src-python/test/test_config_validated_property.py`、`test_config_validation_error.py`、`test_controller_config_validation_decorator.py` |
| CT-05 | 仕様書の一覧（`docs/spec/reference/`）はコードから生成したものと一致する | この仕様書 | `tests/devtools/test_spec_catalog.py`（`python tools/spec_catalog.py --check`） |

## 利用者の操作と同意

| ID | 契約 | 根拠 | 確かめているもの |
|---|---|---|---|
| CT-10 | モデルの取得は、ライセンスとサイズを示して同意を得てから行う。起動時の自動取得も明示の同意が要る | `AGENTS.md`「ユーザーの操作と同意」 | `tests/voice/test_model_download_policy.py`、`test_model_downloads.py`、`src-ui/logics/common/modelConsentTranslations.test.js` |
| CT-11 | 取得できるモデルは版、サイズ、SHA-256、ライセンスを固定してカタログに載せる。非商用など制限のあるライセンスのモデルは既定にしない | `AGENTS.md`「配布物とライセンス」 | `tests/voice/test_model_downloads.py`、`tests/voice/test_ocr_model_catalog.py`、`src-ui/logics/configs/ctranslate2License.test.js` |
| CT-12 | 画面の変更によって、マイクの有効化、モデルの取得、メッセージの送信、音声経路の変更が勝手に起きない | `AGENTS.md`「ユーザーの操作と同意」 | 手動 |
| CT-13 | ホットキーは既定で割り当てない。設定画面を開いている間は無効にする | `docs/voice-stack/quick-chat-design.md` | `tests/voice/test_quick_chat_config.py`（既存の割り当ての引き継ぎ）、手動 |
| CT-14 | クラウドへ送るのは、利用者がキーを登録してエンジンを選んだときだけ | `docs/transcription_stt_api_integration_plan.md` | `src-ui/logics/configs/cloudTranscription.test.js`、手動 |

## 停止と独立した制御

| ID | 契約 | 根拠 | 確かめているもの |
|---|---|---|---|
| CT-20 | 停止の要求（`stop_voice`、`mute_voice`など）は、ほかの処理を待たずにすぐ処理する | `PRODUCT.md`、`DESIGN.md` | `tests/voice/test_priority_cancel.py` |
| CT-21 | 「読み上げ停止」は読み上げだけを止め、読み上げのオンオフとミュートは変えない。停止の前に積まれた音声はあとで鳴らない | `docs/superpowers/specs/2026-10-27-managed-voice-route-design.md` | `tests/voice/test_managed_route.py`、`tests/voice/test_tts_toggle.py` |
| CT-22 | 読み上げ（TTS）とRVCは独立したスイッチで、片方の操作がもう片方を止めない | `AGENTS.md`「停止と独立した制御」 | `tests/voice/test_direct_voice_controller.py` |
| CT-23 | ミュートは確認できるまで解除しない。管理対象の経路では読み上げと変換音声の両方を止め、再起動後も続く | `docs/voice-stack/adr-005-managed-microphone-lifetime.md` | `tests/voice/test_managed_route.py`、`tests/voice/test_mute_state.py`、`tests/voice/test_pipewire_gate.py` |
| CT-24 | Quick Chat、VRパネル、ホットキーの振る舞いを保つ | `AGENTS.md`、`PRODUCT.md` | `tests/voice/test_quick_chat_ui.py`、`src-ui/logics/common/vrPanelWire.test.js`、手動 |

## 秘密情報と安全

| ID | 契約 | 根拠 | 確かめているもの |
|---|---|---|---|
| CT-30 | APIキーとトークンの値をログに書かない。会話の本文を診断ログに書かない | `src-python/utils.py` | `src-python/test/test_utils_log_masking.py` |
| CT-31 | VRパネルからは、APIキー、トークン、モデル取得、ファイルを開く操作、終了、更新を要求できない | `src-ui/logics/common/vrPanelWire.js` | `src-ui/logics/common/vrPanelWire.test.js` |
| CT-32 | WebSocketはトークンのない接続を拒み、すべてのアドレスでは待ち受けない | `src-python/models/websocket/websocket_server.py` | `src-python/test/test_websocket_auth_and_bind_guard.py` |
| CT-33 | 上流VRCTのチャット吹き出し検出モデルを含むOCRの重み、許諾のないモデル、Mia2026の音声を配布物に入れない | `AGENTS.md`「配布物とライセンス」 | `tests/voice/test_ocr_distribution.py`、`tests/voice/test_distribution_artifacts.py` |

## 画面と文言

| ID | 契約 | 根拠 | 確かめているもの |
|---|---|---|---|
| CT-40 | 表示する文言は`locales/`に置き、`en.yml`と`ja.yml`は必ずそろえる | `AGENTS.md`「UI」 | `tests/voice/test_headless_and_ui_contract.py`、`src-ui/logics/configs/cloudTranscription.test.js` |
| CT-41 | React 18、CSS Modules、Jotai、i18nextの構成を保ち、リモートのフォントを入れない | `AGENTS.md`「UI」 | 手動 |
| CT-42 | 言語の変更は要求ごとに対応づけ、失敗したら読み直す | `src-ui/logics/main/languageMutationCoordinator.js` | `languageMutationCoordinator.test.js`、`languageMutations.test.js` |
| CT-43 | 未保存の変更があるまま離れるときは確かめる | `cross-cutting.md` | `src-ui/logics/voice/saveBar.test.js`（保存バーの集計）、手動（ダイアログ） |
