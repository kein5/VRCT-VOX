# IPCプロトコル（UIとサイドカー）

UI（Tauri＋React）とPythonのサイドカーの間のメッセージの規則。個々のエンドポイントは[IPCエンドポイント一覧](reference/ipc-endpoints.md)、エラーコードは[エラーコード一覧](reference/error-codes.md)にある。

LSPの仕様書が「Base Protocol」と各メッセージの説明を分けているのにならい、この文書は全エンドポイントに共通する規則だけを書く。

## 経路

```mermaid
flowchart LR
  subgraph Tauri["Tauri（Rust）"]
    main["main ウィンドウ（React）"]
    vr["vr_panel ウィンドウ"]
    qc["quick_chat ウィンドウ"]
  end
  side["サイドカー（Python, bin/vrct-vox-sidecar）"]
  main -- "stdin: 要求（1行のJSON）" --> side
  side -- "stdout: 応答と通知（1行のJSON）" --> main
  side -- "stderr: 警告とエラー" --> main
  vr -- "Tauriイベント vr-panel-stdout" --> main
  qc -- "Tauriコマンド quick_chat_submit" --> main
```

- サイドカーと話すのは`main`ウィンドウだけである。VRパネルとQuick Chatは`main`を経由する（[外部インターフェース](external-interfaces.md#ウィンドウ間の連携)）。
- 起動は`Command.sidecar("bin/vrct-vox-sidecar")`（`src-ui/views/app/_app_controllers/StartPythonController.jsx`）。

## メッセージの形

### 要求（UI → サイドカー、stdin）

```json
{"endpoint": "/set/data/osc_port", "data": "OTAwMQ=="}
```

| 項目 | 型 | 内容 |
|---|---|---|
| `endpoint` | 文字列 | 要求するエンドポイント |
| `data` | 文字列（省略可） | 値を`JSON.stringify`したものをBase64にした文字列。値がない要求では省略する |

- 1行に1つのJSONを書き、改行で終える（`src-ui/logics/common/useStdoutToPython.js`）。
- サイドカーは`data`をBase64から戻してJSONとして読む（`encodeBase64`、`src-python/utils.py`）。読めないときは空の辞書になる。
- 要求に通し番号はない。応答は`endpoint`で対応づける。同じエンドポイントへの要求が重なったときの対応づけは、言語の変更だけUI側で管理している（後述）。

### 応答と通知（サイドカー → UI、stdout）

```json
{"status": 200, "endpoint": "/set/data/osc_port", "result": 9001}
```

| 項目 | 型 | 内容 |
|---|---|---|
| `status` | 数値 | 状態コード（次の表） |
| `endpoint` | 文字列 | 応答なら要求と同じエンドポイント、通知なら`/run/…` |
| `result` | 任意 | 結果。エラーのときはエラーの本体 |

応答と通知は同じ形である。通知は要求に対する応答ではなく、サイドカーが自分から送るもので、LSPやJSON-RPCの「Notification」にあたる（UIは返事をしない）。

### 状態コード

| `status` | 意味 | UIの扱い（`useReceiveRoutes.js`） |
|---|---|---|
| 200 | 成功 | エンドポイントに登録された受信先へ`result`を渡す。受信先がなければ`Invalid endpoint`としてコンソールに出す |
| 400 | 想定されたエラー | `result.error_code`で振り分ける（[横断的な振る舞い](cross-cutting.md#エラーの扱い)） |
| 404 | 存在しないエンドポイント | `result`は`"Invalid endpoint"` |
| 409 | 状態が合わず実行できない（音声系） | 音声・RVC・音声サーバーの各画面が`result.error_code`を表示する |
| 423 | ロック中（初期化前、または同じ機能が処理中） | 待っても解けなかったときだけ届く（後述） |
| 500 | 想定外の例外 | 再起動を勧める通知を出す |
| 348 | ログ | 表示しない。`{"status": 348, "log": …, "data": …}`の形で`endpoint`を持たない |

音声・RVC・リアルタイム音声認識・モデル取得のエンドポイントは、200以外を受け取ると`errorHandling_Backend`ではなく各機能のエラー表示に回る（`receiveRoutes`の先頭の分岐）。

### エラーの本体

```json
{"status": 400, "endpoint": "/set/data/osc_port", "result": {
  "error_code": "VALIDATION_OSC_PORT_INVALID",
  "message": "OSC port is not valid",
  "data": 9000,
  "details": {},
  "category": "validation",
  "severity": "error"
}}
```

- `VRCTError.create_error_response`（`src-python/errors.py`）が作る。`message`は英語の既定文で、UIは多くの場合`locales/`の文言に置き換える。
- `data`は「元に戻すべき値」である。設定の検証エラーでは保存前の値が入り、UIはその値で画面を巻き戻す。
- 音声系の409は`{"error_code": "..."}`だけを返すことがある。
- 例外から作ったエラーは`details.exception_type`を持つ。

## エンドポイントの名前

| 形 | 意味 | 例 |
|---|---|---|
| `/get/data/<名前>` | 値を読む | `/get/data/osc_port` |
| `/set/data/<名前>` | 値を書く。応答の`result`は保存後の値 | `/set/data/osc_port` |
| `/delete/data/<名前>` | 値を消す（APIキーなど） | `/delete/data/deepl_auth_key` |
| `/set/enable/<名前>`、`/set/disable/<名前>` | 機能のオンとオフ | `/set/enable/translation` |
| `/run/<名前>` | 操作、または通知 | `/run/send_message_box`、`/run/initialization_complete` |

- `/run/…`は要求にも通知にも使う。どちらであるかは[一覧](reference/ipc-endpoints.md)で区別している。
- 通知の名前は`run_mapping`（`src-python/mainloop.py`）にあり、サイドカーは`controller.run(status, run_mapping[名前], result)`で送る。`run_mapping`にない名前を使うと送る時点で例外になるため、`src-python/test/test_controller_run_mapping_contract.py`が名前の存在を確かめる。

## 起動と初期化

```mermaid
sequenceDiagram
  participant UI as UI（main）
  participant S as サイドカー
  UI->>S: 起動（spawn）
  Note over S: 受信スレッドと処理ワーカー3本が先に動き出す
  S-->>UI: /run/connected_network
  S-->>UI: /run/initialization_progress（1〜4）
  S-->>UI: /run/enable_ai_models
  S-->>UI: /run/selected_translation_engines ほか
  S-->>UI: /run/initialization_complete {"/get/data/…": 値, …}
  Note over S: ここで全エンドポイントのロックを外す
  UI->>S: /run/feed_watchdog（20秒ごと）
```

1. サイドカーは受信スレッドと処理ワーカーを動かしてから`controller.init()`を実行する。初期化の間に届いた要求のうち、`mapping`で`"status": False`のもの（翻訳・音声認識のオンオフ、メッセージ送信など）はロック中として扱う。
2. 初期化の最後に、ほぼすべての`/get/data/…`の結果を1つにまとめた`/run/initialization_complete`を送る。ネットワークを使う`available_releases`と、画面の調査をする`ocr_readiness`は含めない（`_INIT_MAPPING_EXCLUDED_ENDPOINTS`）。値を取れなかった項目は`null`になる。
3. UIは`/run/initialization_complete`の各項目を対応する受信先に配り、`IsBackendReady`を真にして起動画面を閉じる。音声・音声サーバー・リアルタイム音声認識・モデル取得の状態は、このときUIから改めて取りに行く。
4. 全エンドポイントのロックが外れるのは`init()`が戻ったあとである。

## 並行性とロック

- 要求はキューに入り、3本のワーカー（`DEFAULT_WORKER_COUNT`）が順に処理する。届いた順に終わるとは限らない。
- エンドポイントごとにロックがある。`/set/enable/x`と`/set/disable/x`は同じロックを使う。同じロックが使用中なら0.05秒ごとに入れ直し、400回（約20秒）待っても取れなければ423を返す。
- 初期化前のロック（`"status": False`）に当たった要求は0.1秒ごとに入れ直し、300回（約30秒）で423を返す。
- 次の要求はキューを通らず、受信した時点で処理する。止める操作が、ほかの重い処理の後ろで待たないためである: `/run/stop_voice`、`/run/disable_tts`、`/run/mute_voice`、`/run/resume_voice`、`/run/stop_direct_voice`、`/run/stop_realtime_asr`、`/run/stop_speech_server`。
- 受信スレッドは一部の要求に世代番号を付ける（`/run/send_message_box`の`_voice_generation`など）。キューで待つ間に停止操作があった要求の音声を、あとから鳴らさないためである（[横断的な振る舞い](cross-cutting.md#停止とミュート)）。

### 言語の変更の対応づけ

`selected_your_languages`、`selected_target_languages`、`selected_translation_engines`、`selected_tab_no`への書き込みだけは、UIが要求ごとにIDと送る前の状態を覚えておく（`src-ui/logics/main/languageMutationCoordinator.js`）。400・404・423・500が返ったときは、言語に関する値をすべて読み直す。30秒以内に応答がないときは「未確認」として示すが、要求の持ち主は手放さず、最後の応答を待つ。遅れて届いた応答を別の要求のものと取り違えないためである。そのため応答が失われると、サイドカーを起動し直すまで言語を変えられない。IDはサイドカーには送らない。

## 監視と終了

- UIは起動後20秒ごとに`/run/feed_watchdog`を送る。サイドカーは60秒届かなければ自分を止める（`WATCHDOG_TIMEOUT`、`WATCHDOG_INTERVAL`）。止める処理が30秒で終わらなければプロセスを強制終了する。
- UIの閉じるボタンは`/run/shutdown`を送り、2秒待ってからウィンドウを閉じる。
- stdinが閉じてもサイドカーの受信は終わらない。UIが落ちた場合にサイドカーを止めるのは監視の役目である。
- サイドカーのプロセスが終わると、UIは`/run/shutdown`か`/run/update_software`を送った後でない限り、処理部分が停止したので再起動が要ることを消えない通知で知らせる（`StartPythonController.jsx`）。

## stderrとログ

- stderrの行のうち、警告と判定したもの（`src-ui/logics/common/sidecarDiagnostics.js`）は無視する。それ以外の行は、消えないエラー通知として表示する。
- status 348の行はログで、UIは表示しない。同じ内容が`process.log`にも書かれる。
- ログではAPIキーなどの値を伏せる（`SENSITIVE_ENDPOINT_MARKERS`）。会話の本文は`process.log`に書かない。stdoutのIPCそのものは伏せない。
