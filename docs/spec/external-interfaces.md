# 外部インターフェース

VRCT-VOXが他のプログラムとやり取りする口。UIとサイドカーの間は[IPCプロトコル](ipc-protocol.md)にある。

## VRChatへのOSC

`src-python/models/osc/osc.py`（python-osc、OSCQueryは任意のtinyoscquery）。

| 方向 | アドレス | 引数 | 送る条件 |
|---|---|---|---|
| 送信 | `/chatbox/input` | `[文字列, true, 通知音]` | 「VRChatにメッセージを送信する」がオン（入力欄とマイク）、または「受信したメッセージをVRChatに送信する」がオン（スピーカー）。空の文字列は送らない |
| 送信 | `/chatbox/typing` | `[真偽]` | 入力中の表示。`true`は「VRChatにメッセージを送信する」がオンのときだけ送る。アプリがオンにした表示を消す`false`は、送信設定がオフになった後も送る |
| 受信 | `/avatar/parameters/MuteSelf` | 真偽 | VRCマイクミュート同期 |
| 受信 | `/avatar/change` | — | アバターが変わったら`MuteSelf`を読み直す |

- 送信先は`OSC_IP_ADDRESS`と`OSC_PORT`（既定`127.0.0.1:9000`）。通知音は`NOTIFICATION_VRC_SFX`。
- 入力欄の送信操作では、空欄や送信失敗の場合も入力中の表示を消す。空欄への変更、自動クリア、フォーカスの移動、VRChatへの送信をオフにする操作でも消す。入力中の通知は引き続き2秒以上の間隔を空ける。Quick Chatは入力中の通知を出さず、送信時は共通の処理で表示を消す。
- OCRで読んだ文とリアルタイム字幕はVRChatへ送らない。
- 「翻訳後のメッセージのみ送信する」がオンなら訳だけを送る。送る文の形は設定のVRChatページのメッセージフォーマットで決める。
- 送信先と受信のbind先は独立している。OSCQueryは送信先が`127.0.0.1`か`localhost`のときだけ使い、UDP受信とHTTPを常に`127.0.0.1`の空きポートにbindする。`VRCT:<時刻>`という名前で受信口を公開する。送信先を別のマシンから戻した場合も、受信はloopbackで再開する。
- OSCの起動、IP・ポート変更、停止は同じライフサイクルロックで直列化する。新しい受信・広告を用意できてから設定を確定し、失敗したら前の受信・広告を復旧する。復旧も失敗した場合は設定値を保ち、capabilityを無効として知らせる。終了要求後の起動は拒否する。
- bundleの時刻によって受信を待たせず、中のメッセージを受信時に処理する。受信は1本のスレッドで行い、そのスレッドは作成時のサーバーだけを使う。
- HTTPには1要求あたり2秒の読み取り期限を設ける。交換・停止・途中の初期化失敗では、UDPとHTTPを閉じ、広告を解除してZeroconfを閉じ、探索ブラウザーも止める。後始末の待機は2秒まで。終わらなければ所有者への参照を保ち、後始末が終わるまで置き換えない。終了時に起動・設定変更のロックを待つ時間も2秒までとする。
- capabilityは、UDP受信、HTTP、OSCQuery広告、探索ブラウザーの準備がすべて成功した場合だけ有効になる。UIの初期値も無効である。送信先が非ローカル、tinyoscqueryがない、bindや広告に失敗した場合は、起動時と設定変更後に`/run/enable_osc_query`で`{"data": false, "disabled_functions": ["vrc_mic_mute_sync"]}`を送り、理由と再設定の案内を表示する。同期がオンだった場合はマイク入力を停止してから同期をオフにし、両スイッチの状態も通知する。自動で文字起こしを再開しない。その状態で同期をオンにすると`VRC_MIC_MUTE_SYNC_OSC_DISABLED`になる。
- ミュート同期がオンでVRChat側がミュート中のときは、マイクの認識結果を捨てる。
- `MuteSelf=true`はすぐにミュート状態へ反映し、マイクの文字起こしを一時停止する。ミュート中に届いた`false`だけでは再開せず、下記の条件で確認したローカルのVRChatのOSCQueryで`/avatar/parameters/MuteSelf`を読み直し、真偽値の`false`を確認した場合だけ再開する。到達できない、値がない、値が真偽値でない、時間切れの場合はミュートを保ち、`printLog`に理由を記録する。
- 探索結果は、解決済みのIPv4アドレスがすべてloopbackで、サービス名が`VRChat-Client`またはその識別子付きの名前に一致するものだけをHTTPで確認する。`HOST_INFO.NAME`がサービス名と一致し、`OSC_IP`がloopback、`OSC_PORT`が設定した送信ポート、`OSC_TRANSPORT`が`UDP`であることを確かめる。候補を1つに絞れなければ解除しない。LANの広告と名前の部分一致だけの広告は問い合わせず、HTTPのリダイレクトや環境変数のプロキシも使わない。これはローカルプロセスを信頼する境界であり、VRChatプロセスの暗号学的な認証ではない。
- OSCQueryの待ち時間はサービス探索とライフサイクルロックの待機を含めて2秒。確認はOSCの受信スレッドとマイク操作のキューの外で行い、確認中に届いた`true`は古い結果より優先する。時間切れの結果は後から届いても使わない。通信自体を中断できないため、処理中の問い合わせは1件までとし、それが終わるまでは新しい問い合わせも値を取得できない扱いにする。
- `/avatar/change`ではまずミュートにして、再読み込みを予約する。実行中または待機中のジョブは1件にまとめ、追加の通知は最新の世代だけを保持する。問い合わせ前と結果の反映前に世代を確かめ、後から届いた`true`を上書きしない。停止時には受付を閉じ、待機中のジョブを取り消し、executorも終了する。問い合わせから探索ブラウザーを作り直すことはない。
- 同期のオン・オフ、起動時の同期、受信による変更は、マイクの開始・停止・デバイス変更と共通のControllerロックを通して一時停止・再開する。受信からの操作はマイク操作キューを使う。問い合わせを待つ間はマイクのロックを保持しない。起動時や同期をオンにした直後など状態が不明な間も、文字起こしを一時停止して結果の配送を止める。
- 送る文の長さに上限や分割の処理はない。VRChat側の制限への対応は[未決事項](open-issues.md)にある。

## WebSocketサーバー

`src-python/models/websocket/websocket_server.py`。他のアプリに会話を配信する。

| 項目 | 内容 |
|---|---|
| 有効化 | `WEBSOCKET_SERVER`（既定オフ）。OBSブラウザソースをオンにすると一緒にオンになる。待ち受けの開始を最大6秒待ち、時間切れや停止要求では起動を取り消してオンにしない。ホストやポートの変更でbindできなければ、元のアドレスで立て直してエラーを返す |
| 待ち受け | `WEBSOCKET_HOST`（既定`127.0.0.1`。IPv4のみ。`0.0.0.0`、IPv6、ホスト名は拒否）、`WEBSOCKET_PORT`（既定2231、整数の1〜65535） |
| 認証 | 接続時に`?token=<WEBSOCKET_AUTH_TOKEN>`を付ける。合わなければ接続前にHTTP 403。トークンは初回起動時に作り、設定画面では伏せて表示する。保存値がnull・空白だけ・空文字列・文字列以外なら、新しく生成した既定の秘密値を保存する。空でないトークンがなければサーバーを起動しない |
| 受信 | 受け取るが何もしない。1メッセージの上限は64 KiB |
| 送信 | 処理したメッセージごとに[メッセージの形](data-and-persistence.md#websocketとobsへ送るメッセージ)を全クライアントへ送る。OBSの表示設定が変わると`SETTINGS_UPDATED`を送る |

ホストとポートは[ネットワーク設定](data-and-persistence.md#ネットワーク設定)の検証に通ってから保存・再起動する。WebSocketとOBSをIPv4に統一し、bindの事前確認とコピーするURLの形式をそろえる。

起動中はまだ待ち受けず、期限内に準備が終わった場合だけ接続を受け付ける。取り消した起動が遅れて完了しても待ち受けを始めない。ループとソケットはその起動のスレッドで閉じ、終了を最大2秒待つ（起動待ちの6秒とは別枠）。中断できない処理が残った場合は参照を保ち、終了するまで再起動を失敗として返す。起動中の無効化やホスト・ポート変更でも、変更前の起動を取り消す。

### 送信の上限

上限は`websocket_server.py`の定数で定める。会話本文を切り詰めたり、待っているメッセージを黙って捨てたりはしない。

| 対象 | 上限・動作 |
|---|---|
| 1メッセージ | UTF-8で256 KiB（`_MAX_OUTGOING_MESSAGE_SIZE`）。超える送信は受付時に`BufferError`で拒否する |
| 送信受付全体 | 128件（`_MAX_PENDING_MESSAGES`）かつUTF-8で4 MiB（`_MAX_PENDING_BYTES`）。ループで実行を待つコールバック、送信キュー、配信中の1件を含む。`send()`と`broadcast()`は同じ枠を使う。満杯なら待たずに`BufferError`を返し、会話の出力処理は既存の`MESSAGE_OUTPUT_FAILED`でWebSocketへの出力失敗を通知する |
| 接続ごとの送信バッファ | 1 MiB（`_MAX_CLIENT_BUFFER_BYTES`）。次のメッセージとフレームヘッダーの余裕14バイトを加えて上限を超える接続は、書き込む前にtransportをabortして切断する。圧縮は無効。正常に読み続けるクライアントには、受け付けたメッセージを順番にすべて送る |
| 生存確認 | 20秒ごとにping（`_PING_INTERVAL`）。ping送信開始からpong受信まで20秒（`_PING_TIMEOUT`）。送信バッファが空くのを待つ時間も含め、時間切れならtransportをabortする。closeフレームの送信完了は待たない |

配信は32接続ごと、および1メッセージごとにループへ制御を返す。遅い接続のdrainを他の接続が待つことはない。上記はアプリケーションのバッファと受付の上限であり、OSのソケットバッファや総接続数の上限ではない。

## OBSブラウザソース

`src-python/models/obs/obs_browser_source_server.py`。配信画面に字幕を出すHTMLを配る。

- `OBS_BROWSER_SOURCE`（既定オフ）、`OBS_BROWSER_SOURCE_PORT`（既定2232、整数の1〜65535）。待ち受けるアドレスは`WEBSOCKET_HOST`と同じ。
- OBSとWebSocketのオン・オフ、両サーバーのホスト・ポート変更は[同じIPCロック](ipc-protocol.md#並行性とロック)で直列に処理する。WebSocketをオフにするとOBSもオフになる。OBSだけをオフにしてもWebSocketは止めない。
- OBSの有効化が失敗したら、その試行で新しく起動したWebSocketを停止する。もともと動いていたWebSocketは維持する。有効化中に依存先のWebSocketを起動できなければ`WEBSOCKET_SERVER_UNAVAILABLE`、OBSのポートを確保できなければ`OBS_BROWSER_SOURCE_PORT_UNAVAILABLE`、OBSの起動に失敗すれば`OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE`を返す。
- WebSocketホストの変更では、有効なOBSも新しいホストで待ち受けを開始してから設定を確定する。OBSの再起動に失敗したら両サーバーを元のホストへ戻し、`OBS_BROWSER_SOURCE_HOST_UNAVAILABLE`を返す。WebSocketの復旧にも失敗したら両方をオフにし、OBSだけ復旧できなければOBSをオフにする。
- OBSポートの変更で再起動に失敗したら、元のポートで復旧を試み、`OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE`を返す。復旧できなければOBSをオフにする。整数でないか1〜65535の範囲外のポートには、設定やサービスを変更する前に`OBS_BROWSER_SOURCE_PORT_INVALID`を返す。失敗した要求の値とUIの待機解除は[エラーの扱い](cross-cutting.md#エラーの扱い)に従う。
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

同梱TTSサーバーの停止・異常終了は、起動ごとの識別子と、その実行を使うTTSの世代を照合して処理する。現在のTTSが使うサーバーが終了したときは、TTSをオフにして待機中・再生中の読み上げを取り消し、従来どおり音声の状態取得でUIに伝える。同じ実行の停止直後と後処理後に通知が重なっても、無効化とTTSの世代更新は一度だけ行う。古い実行からの遅れた通知で、別の接続先や新しいサーバー実行を使うTTSをオフにしない。

TTSのスイッチをオフにしたときは、そのスイッチが起動した同梱サーバーだけを止める。設定画面から起動したサーバーと、独立したRVCのスイッチは維持する。

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

VRパネルで会話ログを閉じている間も、`vr-panel-state`の受信とログの更新は続ける。閉じた領域は描画せず、操作も受け付けない。ログ本体の購読を外し、開き直すと保存した表示位置と末尾への追従状態を戻す。上へスクロールして読んでいた場合はその位置を保ち、それ以外は最新の末尾に追従する。保存中に古い行が保持上限を超えた場合は、通常のログ更新と同じように位置を補正する。

レーザーの位置は最後の`vr-panel-pointer`を保持し、パネル内のスクロール、表示内容の差し替え、レイアウトの変更でもホバー対象を調べ直す。判定は1フレームに1回にまとめ、対象が変わらなければ`data-vr-hover`を書き換えない。ポインタがなくなったらホバー表示を解除する。

### ホットキー

- 動作は5つ: 小窓を開く、VRCT-VOXの最小化と再表示、翻訳・マイク・スピーカーのオンオフ。既定ではどれも割り当てない。
- X11とXWaylandではTauriのグローバルショートカット、ネイティブのWaylandではXDG GlobalShortcuts portalで登録する。KDEでは設定したキーをデスクトップ側にも反映し、反映できなかったときはお知らせを出す。
- 設定画面を開いている間と、サイドカーの準備ができるまでは無効にする。

### 権限

`src-tauri/capabilities/`で、`main`にウィンドウ操作、ショートカット、ファイル、GitHubへのHTTP、サイドカーの起動を許す。`quick_chat`にはイベントの受信だけを許し、コマンドは呼び出し元のウィンドウ名をRust側で確かめる。
