# 外部インターフェース

VRCT-VOXが他のプログラムとやり取りする口。UIとサイドカーの間は[IPCプロトコル](ipc-protocol.md)にある。

## VRChatへのOSC

`src-python/models/osc/osc.py`（python-osc、OSCQueryは任意のtinyoscquery）。

| 方向 | アドレス | 引数 | 送る条件 |
|---|---|---|---|
| 送信 | `/chatbox/input` | `[文字列, true, 通知音]` | 「VRChatにメッセージを送信する」がオン（入力欄とマイク）、または「受信したメッセージをVRChatに送信する」がオン（スピーカー）。空の文字列は送らない |
| 送信 | `/chatbox/typing` | `[真偽]` | 入力中の表示。「VRChatにメッセージを送信する」がオンのとき |
| 受信 | `/avatar/parameters/MuteSelf` | 真偽 | VRCマイクミュート同期 |
| 受信 | `/avatar/change` | — | アバターが変わったら`MuteSelf`を読み直す |

- 送信先は`OSC_IP_ADDRESS`と`OSC_PORT`（既定`127.0.0.1:9000`）。通知音は`NOTIFICATION_VRC_SFX`。
- OCRで読んだ文とリアルタイム字幕はVRChatへ送らない。
- 「翻訳後のメッセージのみ送信する」がオンなら訳だけを送る。送る文の形は設定のVRChatページのメッセージフォーマットで決める。
- 受信は空いているUDPポートで待つ。OSCQueryは送信先が`127.0.0.1`か`localhost`のときだけ使い、`VRCT:<時刻>`という名前で受信口を公開し、mDNSで`VRChat-Client`を探す。
- OSCQueryが使えないと、起動時に`/run/enable_osc_query`で`{"data": false, "disabled_functions": ["vrc_mic_mute_sync"]}`を送り、ミュート同期をオフにする。その状態でオンにすると`VRC_MIC_MUTE_SYNC_OSC_DISABLED`になる。
- ミュート同期がオンでVRChat側がミュート中のときは、マイクの認識結果を捨てる。
- `MuteSelf=true`はすぐにミュート状態へ反映し、マイクの文字起こしを一時停止する。ミュート中に届いた`false`だけでは再開せず、`VRChat-Client`のOSCQueryで`/avatar/parameters/MuteSelf`を読み直し、真偽値の`false`を確認した場合だけ再開する。到達できない、値がない、値が真偽値でない、時間切れの場合はミュートを保ち、`printLog`に理由を記録する。
- OSCQueryの待ち時間はサービス探索を含めて2秒。確認はOSCの受信スレッドとマイク操作のキューの外で行い、確認中に届いた`true`は古い結果より優先する。時間切れの結果は後から届いても使わない。通信自体を中断できないため、処理中の問い合わせは1件までとし、それが終わるまでは新しい問い合わせも値を取得できない扱いにする。
- `/avatar/change`での再読み込みは継続する。この結果も、問い合わせ後に届いた`true`を上書きしない。実際の一時停止と再開は、従来どおりマイク操作のキューとControllerのロックを通す。
- 送る文の長さに上限や分割の処理はない。VRChat側の制限への対応は[未決事項](open-issues.md)にある。

## WebSocketサーバー

`src-python/models/websocket/websocket_server.py`。他のアプリに会話を配信する。

| 項目 | 内容 |
|---|---|
| 有効化 | `WEBSOCKET_SERVER`（既定オフ）。OBSブラウザソースをオンにすると一緒にオンになる。実際にbindできたかを最大5秒待ち、できなければオンにしない。ホストやポートの変更でbindできなければ、元のアドレスで立て直してエラーを返す |
| 待ち受け | `WEBSOCKET_HOST`（既定`127.0.0.1`。`0.0.0.0`などのすべてのアドレスは拒否）、`WEBSOCKET_PORT`（既定2231） |
| 認証 | 接続時に`?token=<WEBSOCKET_AUTH_TOKEN>`を付ける。合わなければ接続前にHTTP 403。トークンは初回起動時に作り、設定画面では伏せて表示する |
| 受信 | 受け取るが何もしない |
| 送信 | 処理したメッセージごとに[メッセージの形](data-and-persistence.md#websocketとobsへ送るメッセージ)を全クライアントへ送る。OBSの表示設定が変わると`SETTINGS_UPDATED`を送る |

## OBSブラウザソース

`src-python/models/obs/obs_browser_source_server.py`。配信画面に字幕を出すHTMLを配る。

- `OBS_BROWSER_SOURCE`（既定オフ）、`OBS_BROWSER_SOURCE_PORT`（既定2232）。待ち受けるアドレスは`WEBSOCKET_HOST`と同じ。
- `GET /`と`GET /obs`は`?token=<WEBSOCKET_AUTH_TOKEN>`が必要。`hmac.compare_digest`で照合し、トークンがないか合わなければ403と短い平文だけを返す。認証前にHTMLやトークンを返さない。
- `GET /health`は認証なしで`ok`だけを返す。それ以外のパスは404。どのパスでも、`Host`がIPアドレスか`localhost`でなければ403（DNSリバインディング対策）。
- HTMLの応答には`Cache-Control: no-store, max-age=0`と`Referrer-Policy: no-referrer`を付ける。アクセスログは出さず、クエリ文字列を記録しない。
- 設定画面からコピーするURLには、WebSocketと同じトークンが入る。画面では伏せて表示する。設定済みのOBSブラウザソースもURLのコピーし直しが必要で、URL欄の下に案内を出す。
- ページはWebSocketサーバーに接続して字幕を受け取る。切れたら0.5秒から1.5倍ずつ、最大8秒の間隔でつなぎ直す。
- 表示の設定と範囲: 最大メッセージ数14（1〜50）、表示時間60秒（1〜120）、フェードアウト12秒（0〜120）、文字の大きさ40（10〜200）、文字色`#FFFFFF`、縁取り3（0〜20）、縁取りの色`#000000`。

## クラウドとネットワークのサービス

| サービス | 接続先 | 認証 | 使う時 |
|---|---|---|---|
| DeepL | DeepLのSDKの既定 | APIキー | キーの確認と翻訳 |
| Plamo | `https://api.platform.preferredai.jp/v1` | APIキー | キーの確認、モデル一覧、翻訳 |
| Gemini | google-genaiのSDK | APIキー | 同上 |
| OpenAI | OpenAIのSDKの既定 | APIキー | 同上 |
| Groq（翻訳） | `https://api.groq.com/openai/v1` | APIキー | 同上 |
| OpenRouter | `https://openrouter.ai/api/v1` | APIキー | 同上 |
| OpenAI互換（翻訳） | `OPENAI_COMPATIBLE_URL` | APIキー | 同上 |
| LM Studio | `LMSTUDIO_URL`（既定`http://127.0.0.1:1234/v1`） | なし | 接続の確認、モデル一覧、翻訳 |
| Ollama | `http://localhost:11434` | なし | 同上 |
| Google（音声認識） | speech_recognitionの既定 | なし | 発話ごと |
| Groq Whisper | `https://api.groq.com/openai/v1` | APIキー | キーの確認（`/models`）と発話ごとの`/audio/transcriptions` |
| OpenAI Whisper | `https://api.openai.com/v1` | APIキー | 同上。`*-transcribe`のモデルには`json`、Whisperには`verbose_json`で要求する |
| カスタムWhisperサーバー | `TRANSCRIPTION_CUSTOM_URL` | APIキー（不要なサーバーでも任意の文字列） | 同上 |
| Deepgram | `https://api.deepgram.com/v1` | `Authorization: Token <キー>` | キーの確認（`/auth/token`）、モデル一覧（`/models`）、発話ごとの`/listen` |
| Hugging Face | `https://huggingface.co/{repo}/resolve/{rev}/{path}` | なし | 利用者が同意したモデルの取得。接続先はhuggingface.coとそのCDNに限る |
| 接続の確認 | `https://www.google.com` | なし | 起動時に1回（3秒） |

- クラウドの音声認識の仕様への準拠は`docs/transcription_stt_api_integration_plan.md`と各サービスの公式文書で確かめる。
- 更新の確認とテレメトリーは送信しない（[横断的な振る舞い](cross-cutting.md#同意と外部への送信)）。

## ローカルの音声サーバー

| 相手 | 起動 | 通信 |
|---|---|---|
| 同梱のspeech.cpp（TTS、ASR） | `build/vrct-vc-worker … speech-server`。プロファイルは`japanese`、`multilingual`、`asr` | OSが割り当てた`127.0.0.1`のポート。`GET /health`、`GET /v1/models`で準備を確かめる。起動の待ち時間は120秒 |
| 外部のspeech.cpp | 利用者が起動する | ループバックの`http`だけを受け付ける |
| 読み上げ | — | `POST /v1/audio/speech`に`{input, voice, language, response_format: "pcm", seed?, instructions?}`。応答は`audio/pcm`。4000文字まで |
| 音声認識（REST） | — | `POST /v1/audio/transcriptions` |
| リアルタイム音声認識 | — | `ws://…/v1/realtime`。`session.update`と`input_audio_buffer.append`、`commit`、`clear` |
| RVCワーカー | `build/vrct-vc-worker … rvc …` | stdin・stdoutでPCM（48kHz、3840フレーム単位）。制御はJSON行（32KiBまで） |

設計の経緯は`docs/voice-stack/`（`current-architecture-2026-10-28.md`、`owned-speech-servers-report.md`、ADR）にある。

## デスクトップとの統合

### ウィンドウ

| ラベル | 入口 | 内容 |
|---|---|---|
| `main` | `src-ui/index.html` | メイン画面と設定画面。閉じるとアプリが終わる |
| `quick_chat` | `src-ui/quick-chat.html` | チャット入力の小窓。ホットキーかボタンで開き、閉じても隠すだけで下書きは残る |
| `vr_panel` | `src-ui/vr.html` | VR UI。画面の外（-10000, -10000）に置いて描画し、オーバーレイが取り込む。VR UIがオンの間だけ作る |

設定画面は別ウィンドウではなく、`main`の中のページである。

### Tauriのコマンド

| コマンド | 呼べるウィンドウ | 働き |
|---|---|---|
| `get_font_list` | `main` | システムのフォント名の一覧 |
| `set_vr_panel_window` | `main` | VRパネルのウィンドウを作る・消す |
| `quick_chat_show`、`quick_chat_configure`、`quick_chat_take`、`quick_chat_finish`、`quick_chat_shortcut_platform` | `main` | 小窓を開く、設定を渡す、送信要求を受け取る、結果を返す、ホットキーの登録方法を調べる |
| `quick_chat_context`、`quick_chat_submit`、`quick_chat_hide` | `quick_chat` | 設定を読む、送信を頼む、隠す |
| `portal_shortcuts_bind` | `main` | Waylandでホットキーを登録する（180秒で打ち切り） |

VRパネルの要求は`main`が中継する。中継しないのは、アプリの終了と更新、ファイルを開く操作、モデルの取得、認証キーとトークン、接続先（`*_url`、WebSocket・OBS・OSCのホストとポート）、音声の設定（読み上げ、直接の音声、音声サーバー、リアルタイム音声認識）である（`src-ui/logics/common/vrPanelWire.js`）。VRパネルへ写す状態にも、認証キーとトークンは入れない。

### ウィンドウ間の連携

| イベント | 向き | 内容 |
|---|---|---|
| `quick-chat-requested` | Rust → `main` | 小窓から送信の要求が来た。`main`は`quick_chat_take`で受け取り、`/run/send_message_box`で送る |
| `quick-chat-result` | Rust → `quick_chat` | `{id, accepted}`。同じIDの再送には前の結果を返す |
| `quick-chat-opened` | Rust → `quick_chat` | 入力欄にフォーカスを戻す |
| `portal-shortcut` | Rust → `main` | Waylandでホットキーが押された |
| `vr-panel-state` | `main` → 全体 | 画面の状態をVRパネルへ写す。会話ログだけは前に送ったログとの差分で、通し番号が合わなければVRパネルが`vr-panel-ready`で全件を頼み直す |
| `vr-panel-ready` | `vr_panel` → `main` | VRパネルの準備ができた。`main`は状態を送り直す |
| `vr-panel-stdout` | `vr_panel` → `main` | VRパネルからの要求。`main`が許可したものだけをサイドカーへ渡す |
| `vr-panel-config-page` | `vr_panel` → `main` | VR内の設定を開いた・閉じた |
| `vr-panel-pointer` | `main` → 全体 | VR内のポインタの位置 |

### ホットキー

- 動作は5つ: 小窓を開く、VRCT-VOXの最小化と再表示、翻訳・マイク・スピーカーのオンオフ。既定ではどれも割り当てない。
- X11とXWaylandではTauriのグローバルショートカット、ネイティブのWaylandではXDG GlobalShortcuts portalで登録する。KDEでは設定したキーをデスクトップ側にも反映し、反映できなかったときはお知らせを出す。
- 設定画面を開いている間と、サイドカーの準備ができるまでは無効にする。

### 権限

`src-tauri/capabilities/`で、`main`にウィンドウ操作、ショートカット、ファイル、GitHubへのHTTP、サイドカーの起動を許す。`quick_chat`にはイベントの受信だけを許し、コマンドは呼び出し元のウィンドウ名をRust側で確かめる。
