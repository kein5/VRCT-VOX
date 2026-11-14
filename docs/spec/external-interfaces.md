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
- capabilityは、UDP受信、HTTP、OSCQuery広告、探索ブラウザーの準備がすべて成功した場合だけ有効になる。UIの初期値も無効である。送信先が非ローカル、tinyoscqueryがない、bindや広告に失敗した場合は、起動時と設定変更後に`/run/enable_osc_query`で`{"data": false, "disabled_functions": ["vrc_mic_mute_sync"], "reason": …, "microphone_stopped": …}`を送る。`reason`は、送信先が別のマシンなら`remote_destination`、このPC宛てなのに準備に失敗したなら`setup_failed`。`microphone_stopped`は、同期がオンだったのでマイク入力を止めた場合に真になる。UIはこの2つで案内の文言を選び、設定画面の同期の欄にも`reason`に合った理由を表示する。別のマシン宛てのときは、OSCの設定を直す案内を出さない。同期がオンだった場合はマイク入力を停止してから同期をオフにし、両スイッチの状態も通知する。ただし、送信先を別のマシンにしたまま起動しただけで、同期がもともとオフだった場合は、`disabled_functions`を空にして送る。何も止めておらず、設定で選んだ状態なので、UIは案内を出さない。この場合もcapabilityは無効で、設定画面の同期の欄には理由を表示する。自動で文字起こしを再開しない。その状態で同期をオンにすると`VRC_MIC_MUTE_SYNC_OSC_DISABLED`になる。
- ミュート同期がオンでVRChat側がミュート中のときは、マイクの認識結果を捨てる。
- `MuteSelf=true`はすぐにミュート状態へ反映し、マイクの文字起こしを一時停止する。ミュート中に届いた`false`だけでは再開せず、下記の条件で確認したローカルのVRChatのOSCQueryで`/avatar/parameters/MuteSelf`を読み直し、真偽値の`false`を確認した場合だけ再開する。到達できない、値がない、値が真偽値でない、時間切れの場合はミュートを保ち、`printLog`に理由を記録する。
- 探索結果は、解決済みのIPv4アドレスがすべてloopbackで、サービス名が`VRChat-Client`またはその識別子付きの名前に一致するものだけをHTTPで確認する。`HOST_INFO.NAME`がサービス名と一致し、`OSC_IP`がloopback、`OSC_PORT`が設定した送信ポート、`OSC_TRANSPORT`が`UDP`であることを確かめる。候補を1つに絞れなければ解除しない。LANの広告と名前の部分一致だけの広告は問い合わせず、HTTPのリダイレクトや環境変数のプロキシも使わない。これはローカルプロセスを信頼する境界であり、VRChatプロセスの暗号学的な認証ではない。
- OSCQueryの待ち時間はサービス探索とライフサイクルロックの待機を含めて2秒。確認はOSCの受信スレッドとマイク操作のキューの外で行い、確認中に届いた`true`は古い結果より優先する。時間切れの結果は後から届いても使わない。通信自体を中断できないため、処理中の問い合わせは1件までとし、それが終わるまでは新しい問い合わせも値を取得できない扱いにする。
- `/get/data/vrchat_osc_presence`は、このPCでOSCを有効にしたVRChatが見えているかを`"found"`・`"not_found"`・`"unknown"`で返す。VRChatは、OSCが有効なあいだだけOSCQueryを公開する。探索で見つけたローカルのVRChat（名前が`VRChat-Client`で始まり、アドレスがloopbackだけのもの）に`HOST_INFO`を問い合わせ、応答があれば`found`にする。閉じたVRChatも探索の結果にはしばらく残るため、応答で確かめる。応答するものがなければ`not_found`を返し、探索へ問い合わせ直す。VRChatは起動時に一度だけ自分を知らせるので、アプリより後に起動したVRChatは、この問い合わせ直しで次回に見つかる。OSCQueryを使っていない（送信先が別のマシン、受信を開始できていない）ときは`unknown`にする。起動時の一括取得には含めない。UIは、設定のVRChatページとメイン画面のクイック設定に言葉で表示し、表示しているあいだ5秒ごとに取得する。「VRChatにメッセージを送信する」がオフのときは取得せず、オフであることを表示する。会話ログの「送信」は送り出したことだけを表すため、届く状態かどうかはこの表示で示す。
- `/avatar/change`ではまずミュートにして、再読み込みを予約する。実行中または待機中のジョブは1件にまとめ、追加の通知は最新の世代だけを保持する。問い合わせ前と結果の反映前に世代を確かめ、後から届いた`true`を上書きしない。停止時には受付を閉じ、待機中のジョブを取り消し、executorも終了する。問い合わせから探索ブラウザーを作り直すことはない。
- 同期のオン・オフ、起動時の同期、受信による変更は、マイクの開始・停止・デバイス変更と共通のControllerロックを通して一時停止・再開する。受信からの操作はマイク操作キューを使う。問い合わせを待つ間はマイクのロックを保持しない。起動時や同期をオンにした直後など状態が不明な間も、文字起こしを一時停止して結果の配送を止める。
- 送る文の長さに上限や分割の処理はない。VRChat側の制限への対応は[未決事項](open-issues.md)にある。

## WebSocketサーバー

`src-python/models/websocket/websocket_server.py`。他のアプリに会話を配信する。

| 項目 | 内容 |
|---|---|
| 有効化 | `WEBSOCKET_SERVER`（既定オフ）。OBSブラウザソースをオンにすると一緒にオンになる。待ち受けの開始を最大6秒待ち、時間切れや停止要求では起動を取り消してオンにしない。ホストやポートの変更でbindできなければ、元のアドレスで立て直してエラーを返す |
| 待ち受け | `WEBSOCKET_HOST`（既定`127.0.0.1`。IPv4のみ。`0.0.0.0`、IPv6、ホスト名は拒否）、`WEBSOCKET_PORT`（既定2231、整数の1〜65535） |
| 暗号化 | ループバック（127.0.0.0/8）では`ws://`のまま。それ以外のアドレスでは、利用者が指定した証明書と秘密鍵で`wss://`（TLS 1.2以上）だけを使う。使える証明書がなければ待ち受けない（[この PC の外での待ち受け](#この-pc-の外での待ち受け)） |
| 認証 | 接続時に`?token=<WEBSOCKET_AUTH_TOKEN>`を付ける。合わなければ接続前にHTTP 403。トークンは初回起動時に作り、設定画面では伏せて表示する。保存値がnull・空白だけ・空文字列・文字列以外なら、新しく生成した既定の秘密値を保存する。空でないトークンがなければサーバーを起動しない。`/run/regenerate_websocket_auth_token`で作り直すと、古いトークンでの接続をすぐに切り、以後は拒否する |
| 受信 | 使わない。アプリは受信の処理を登録せず、受け取ったメッセージはイベントループの上で捨てる（ワーカースレッドに渡さない）。1メッセージの上限は64 KiB。接続ごとに平均で毎秒10件と128 KiBまで、一時的には20件と256 KiBまで受け付ける。どちらかを超えた接続は1008（policy violation）で閉じ、2秒待っても閉じなければtransportをabortする（セキュリティ監査 SEC-06）。上限は`websocket_server.py`の`_INCOMING_*`の定数 |
| 送信 | 処理したメッセージごとに[メッセージの形](data-and-persistence.md#websocketとobsへ送るメッセージ)を全クライアントへ送る。OBSの表示設定が変わると`SETTINGS_UPDATED`を送る |

ホストとポートは[ネットワーク設定](data-and-persistence.md#ネットワーク設定)の検証に通ってから保存・再起動する。WebSocketとOBSをIPv4に統一し、bindの事前確認とコピーするURLの形式をそろえる。

起動中はまだ待ち受けず、期限内に準備が終わった場合だけ接続を受け付ける。取り消した起動が遅れて完了しても待ち受けを始めない。ループとソケットはその起動のスレッドで閉じ、終了を最大2秒待つ（起動待ちの6秒とは別枠）。中断できない処理が残った場合は参照を保ち、終了するまで再起動を失敗として返す。起動中の無効化やホスト・ポート変更でも、変更前の起動を取り消す。

### この PC の外での待ち受け

ループバック以外のアドレスで待ち受けると、同じネットワークで通信を見られる人がトークンと会話を読めてしまう（セキュリティ監査 SEC-01）。そのため WebSocket と OBS は、ループバック以外では TLS だけで待ち受ける（`src-python/models/websocket/tls.py`）。

- 証明書と秘密鍵は`WEBSOCKET_TLS_CERT_FILE`と`WEBSOCKET_TLS_KEY_FILE`（PEMのファイルのパス、既定は空）。同じファイルに両方が入っていてもよい。パスフレーズ付きの鍵は使えない（コンソールで尋ねて止まらないよう、空のパスフレーズで読む）。1 MiBを超えるファイル、通常のファイルでないもの、空のファイルは読まない。
- `/set/data/websocket_tls`は`{"cert_file", "key_file"}`を受け取り、両方を読み込めたときだけ保存する。片方だけ、形の違う要求、読み込めない組は`WEBSOCKET_TLS_INVALID`。両方を空にすると未設定に戻るが、ホストがループバック以外の間は`WEBSOCKET_HOST_NEEDS_TLS`で拒否する。ループバック以外で動いているサーバーは、新しい組で起動し直してから保存する。起動し直せなければ前の組で立て直し、`WEBSOCKET_SERVER_UNAVAILABLE`を返す。エラーの`data`は保存済みの組。
- `/set/data/websocket_host`は、ループバック以外のアドレスに、読み込める証明書がなければ`WEBSOCKET_HOST_NEEDS_TLS`を返し、サーバーを止めない。
- サーバーを起動する処理（`Model.startWebSocketServer`、`Model.startObsBrowserSourceServer`）も同じ確認をする。ループバック以外で証明書を読み込めなければ、待ち受けずに失敗を返す。どの経路からも、平文の待ち受けをLANのアドレスに開かない。
- 起動時、保存済みのホストがループバック以外で証明書を読み込めなければ、ホストを`127.0.0.1`に戻して保存する。初期設定をUIへ渡したあとに、`/set/data/websocket_host`へ`WEBSOCKET_HOST_RESET_WITHOUT_TLS`（`data`は`127.0.0.1`）を送る。以前の版でLANのアドレスを設定していた場合もこの扱いになる。
- 証明書が読めなかった理由はログに理由の種類（`missing`、`unreadable`、`not_a_file`、`size`、`load_failed`）だけを書き、パスやファイルの中身は書かない。
- OBSのHTTPSでは、TLSのハンドシェイクを各要求の処理スレッドで行い、要求全体の5秒の期限に含める。ハンドシェイクを止めたままの接続が、受け付けの処理をふさぐことはない。WebSocketのハンドシェイクの期限は10秒。
- 設定画面がコピーするURLは、ホストがループバックなら`ws://`と`http://`、それ以外なら`wss://`と`https://`。HTTPSで配ったOBSのページは`wss://`で接続し直す。
- OBS用とWebSocket用のトークンは分けない。OBSのページは字幕を受け取るためにWebSocketのトークンを持つので、分けてもOBSのURLを知った人は会話を読める。漏れたときは作り直しで両方を一度に無効にする。

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

- `OBS_BROWSER_SOURCE`（既定オフ）、`OBS_BROWSER_SOURCE_PORT`（既定2232、整数の1〜65535）。待ち受けるアドレスは`WEBSOCKET_HOST`と同じ。ループバック以外ではWebSocketと同じ証明書でHTTPSだけを使う（[この PC の外での待ち受け](#この-pc-の外での待ち受け)）。
- 表示設定の数値は整数に限る。最大メッセージ数は1〜50、表示時間は1〜120秒、フェードアウト時間は0〜120秒、文字サイズは10〜200px、縁取りの太さは0〜20px。IPCでは整数の文字列も受け付け、成功応答と配信通知には保存した整数を返す。範囲外・小数・真偽値は既存の`OBS_BROWSER_SOURCE_*_INVALID`で拒否し、保存も配信もしない。保存ファイルに無効な値があれば、読み込み時に既定値へ戻す。初回表示と開いているページへの更新も同じ範囲を使う。
- OBSとWebSocketのオン・オフ、両サーバーのホスト・ポート変更は[同じIPCロック](ipc-protocol.md#並行性とロック)で直列に処理する。WebSocketをオフにするとOBSもオフになる。OBSだけをオフにしてもWebSocketは止めない。
- OBSの有効化が失敗したら、その試行で新しく起動したWebSocketを停止する。もともと動いていたWebSocketは維持する。有効化中に依存先のWebSocketを起動できなければ`WEBSOCKET_SERVER_UNAVAILABLE`、OBSのポートを確保できなければ`OBS_BROWSER_SOURCE_PORT_UNAVAILABLE`、OBSの起動に失敗すれば`OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE`を返す。
- 保存済みの設定による起動でも、OBSの実際の起動結果を確認する。失敗したらOBSをオフにし、途中まで確保したサーバーを停止する。初期設定をUIへ渡した後に、上記のOBSエラーを通知する。動作しているWebSocketは維持する。
- WebSocketホストの変更では、有効なOBSも新しいホストで待ち受けを開始してから設定を確定する。OBSの再起動に失敗したら両サーバーを元のホストへ戻し、`OBS_BROWSER_SOURCE_HOST_UNAVAILABLE`を返す。WebSocketの復旧にも失敗したら両方をオフにし、OBSだけ復旧できなければOBSをオフにする。
- OBSポートの変更で再起動に失敗したら、元のポートで復旧を試み、`OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE`を返す。復旧できなければOBSをオフにする。整数でないか1〜65535の範囲外のポートには、設定やサービスを変更する前に`OBS_BROWSER_SOURCE_PORT_INVALID`を返す。失敗した要求の値とUIの待機解除は[エラーの扱い](cross-cutting.md#エラーの扱い)に従う。
- `GET /`と`GET /obs`は`?token=<WEBSOCKET_AUTH_TOKEN>`が必要。`hmac.compare_digest`で照合し、トークンがないか合わなければ403と短い平文だけを返す。認証前にHTMLやトークンを返さない。照合には要求ごとに現在のトークンを使うので、作り直した直後から古いトークンは通らない。
- `GET /obs/connection`は`Authorization: Bearer <WEBSOCKET_AUTH_TOKEN>`で同じ照合を行い、現在のWebSocketポートだけを`{"wsPort": 整数}`で返す。トークンは応答に含めず、クエリ文字列による認証は受け付けない。HTMLと同じHost検証とキャッシュ・参照元の制限を使う。
- `GET /health`は認証なしで`ok`だけを返す。それ以外のパスは404。どのパスでも、`Host`がIPアドレスか`localhost`でなければ403（DNSリバインディング対策）。
- HTMLの応答には`Cache-Control: no-store, max-age=0`と`Referrer-Policy: no-referrer`を付ける。アクセスログは出さず、クエリ文字列を記録しない。
- 設定画面からコピーするURLには、WebSocketと同じトークンが入る。画面では伏せて表示する。設定済みのOBSブラウザソースもURLのコピーし直しが必要で、URL欄の下に案内を出す。
- HTTPの同時処理は16件までとし、超過した接続は閉じる。読み取りの待機は5秒、要求全体も5秒を期限とし、0.1秒周期で期限を確認して未完了の接続を閉じる。停止時は新規受付を止め、受け付けた接続を閉じて、待受処理と各要求の終了を合計2秒まで待つ。残った処理があれば所有者を保持し、終了するまで次の起動を認めない。
- ページはWebSocketサーバーに接続して字幕を受け取る。切れたら0.5秒から1.5倍ずつ、最大8秒の待ち時間で再試行する。毎回`/obs/connection`から現在のポートを取り直すため、変更通知を受け取れなくても新しいポートへ接続できる。再取得は5秒で打ち切り、認証失敗・不正な応答・通信失敗でも同じ待ち時間で再試行する。
- 表示の設定と範囲: 最大メッセージ数14（1〜50）、表示時間60秒（1〜120）、フェードアウト12秒（0〜120）、文字の大きさ40（10〜200）、文字色`#FFFFFF`、縁取り3（0〜20）、縁取りの色`#000000`。

## クラウドとネットワークのサービス

| サービス | 接続先 | 認証 | 使う時 |
|---|---|---|---|
| DeepL | `https://api.deepl.com`（Freeキーは`https://api-free.deepl.com`） | APIキー | キーの確認と翻訳 |
| Plamo | `https://api.platform.preferredai.jp/v1` | APIキー | キーの確認、モデル一覧、翻訳 |
| Gemini | `https://generativelanguage.googleapis.com`（Developer API） | APIキー | 同上 |
| OpenAI | `https://api.openai.com/v1` | APIキー | 同上 |
| Groq（翻訳） | `https://api.groq.com/openai/v1` | APIキー | 同上 |
| OpenRouter | `https://openrouter.ai/api/v1` | APIキー | 同上 |
| OpenAI互換（翻訳） | `OPENAI_COMPATIBLE_URL` | APIキー | 同上 |
| LM Studio | `LMSTUDIO_URL`（既定`http://127.0.0.1:1234/v1`） | なし | 接続の確認、モデル一覧、翻訳 |
| Ollama | `http://localhost:11434` | なし | 同上 |
| Google（音声認識） | `https://www.google.com/speech-api/v2/recognize` | 利用者によるキー登録は不要（speech_recognition同梱の汎用キー） | Google を明示選択して文字起こしをオンにした後、マイク／スピーカーのFLAC音声と言語を送信。候補言語や暫定結果で複数回呼ぶ場合がある。未選択や他エンジンの失敗では使わない |
| Groq Whisper | `https://api.groq.com/openai/v1` | APIキー | キーの確認（`/models`）と発話ごとの`/audio/transcriptions` |
| OpenAI Whisper | `https://api.openai.com/v1` | APIキー | 同上。`*-transcribe`のモデルには`json`、Whisperには`verbose_json`で要求する |
| カスタムWhisperサーバー | `TRANSCRIPTION_CUSTOM_URL` | APIキー（不要なサーバーでも任意の文字列） | 同上 |
| Deepgram | `https://api.deepgram.com/v1` | `Authorization: Token <キー>` | キーの確認（`/auth/token`）、モデル一覧（`/models`）、発話ごとの`/listen` |
| Hugging Face | `https://huggingface.co/{repo}/resolve/{rev}/{path}` | なし | 利用者が同意したモデルの取得。接続先はhuggingface.coとそのCDNに限る |
| 接続の確認 | `https://huggingface.co/`へのHEAD | なし | 起動時の自動取得がオンで、固定版への保存済み同意があり、ファイルが不足している場合だけ1回（3秒）。プロキシ・リダイレクトは使わない |

- クラウドの音声認識の仕様への準拠は`docs/transcription_stt_api_integration_plan.md`と各サービスの公式文書で確かめる。
- OpenAI互換の音声認識では、接続と接続プールの待機を10秒、読み取りとアップロードの書き込みを60秒でタイムアウトさせる。通信が進まない時間の上限であり、SDKの再試行を含む要求全体の期限ではない。
- ローカルWhisper、OpenAI互換、Deepgramの自動検出結果は、返された言語名・コードを選択済みの言語と国に照合する。大文字小文字や`_`と`-`の違いを揃え、地域・文字体系まで一致する候補を優先する。ベース言語しか分からない場合は、その言語に一致する最初の候補を使う。検出言語がない、または選択候補に一致しない場合は、本文を保持し、内部の認識結果の`language`を`None`とする。従来のマイク・スピーカー認識では、配送時の設定スナップショットでもこの不明な値を保ち、先頭の候補言語を推測で付けない。要求で言語を明示した場合は、その指定を使う。
- Deepgramの成功応答でも、結果の構造、文字列の本文、0〜1の有限な数値の信頼度が揃わなければ`TRANSCRIPTION_API_SERVER_ERROR`として扱い、既存の音声パイプラインのエラー経路に渡す。構造が正しい空の本文は、通常の「認識結果なし」として扱う。応答本文や秘密情報は診断ログに残さない。
- 自動取得を予定していない起動では接続確認を送らない。`/run/connected_network`の`null`は未確認、真偽値は取得ホストへの確認結果を表す。UIは`false`のときだけ接続エラーを表示する。この値だけでGoogle音声認識などを使えない状態にはせず、各要求の成否で判定する。
- 公式APIの接続先はコードで固定する。環境変数によるOpenAI・GeminiのURL変更、LangSmith gateway、OllamaのAPIキーは使わない。クラウドHTTPSではシステムのプロキシを使える。Requestsの認証は登録済みヘッダーを保ち、netrcの認証情報へ置き換えない。localhostとローカルIPアドレスへのAPI接続ではプロキシを使わない。APIのリダイレクトは追わず、モデル取得だけは既存のHTTPSホスト許可リストに従う。
- カスタムURLの許可範囲と保存時の扱いは[ネットワーク設定](data-and-persistence.md#ネットワーク設定)を参照する。
- 更新の確認は送信しない（[横断的な振る舞い](cross-cutting.md#同意と外部への送信)）。

### 利用状況の通知

送るかどうかの条件は[横断的な振る舞い](cross-cutting.md#同意と外部への送信)にある。受け側はVRCT-VOXのもの（Cloudflare Workers）で、このリポジトリの外で管理している。受け側の検査の規則を変えるときは、先に受け側の担当と合わせる。

| 項目 | 内容 |
|---|---|
| 宛先 | `POST https://vrct-vox-telemetry.kei9d09.workers.dev/v1/events`。接続先はコードで固定する |
| 鍵 | ヘッダー`X-Ingest-Key`。アプリに埋め込む公開の値で、2種類の通知を送る以外の権限はない |
| 本文 | `{"event": "app_started", "v": 2, "timestamp", "app_version", "os", "os_version", "locale", "hw"}`。`error`はこれに`error_code`（`[A-Za-z0-9_.-]{1,64}`）が付く |
| `timestamp` | 通知を組み立てた時刻。ISO 8601のUTCで、秒まで（`YYYY-MM-DDTHH:MM:SSZ`） |
| `hw` | `{"cpu", "cores", "ram_gb", "gpus": [{"name", "kind", "vram_gb", "driver"}]}`。読み取れた項目だけが入り、何も読めなければ`hw`ごと省く。名前は表示できるASCIIの64文字まで。`ram_gb`は一般的な容量の段階に丸める。`gpus`は4台まで。`kind`は`gpu`か`igpu`。`driver`はWindowsではレジストリにあるディスプレイアダプターのドライバのバージョン、LinuxではNVIDIAのドライバのバージョンだけ |
| `os`と`locale` | `os`は`Windows`、`Linux`、`Other`のどれか。`locale`は表示言語を5種類のタグ（`en-US`、`ja-JP`、`ko-KR`、`zh-CN`、`zh-TW`）にしたもの |
| 応答 | `200 {"ok": true, "accepted": N}`。鍵がなければ401、JSONでなければ400。検査に通らない通知は`accepted`に数えない |
| 通信 | 1件につき1回のPOST。タイムアウトは5秒。リダイレクトは追わず、プロキシは使わない。失敗しても再送しない |

- 2種類以外の通知と、形式に合わないエラーコードは、送る前に捨てる。
- PCの構成は同梱のspeech.cppの`speech devices --json`から読む（[モデル取得の目安](../voice-stack/model-downloads.md)と同じ一覧）。起動は待たせず、最初の通知の前に1回だけ読む。
- デプロイ済みの受け側は、知らない項目が付いた通知も受け付ける（2026-11-14に`v`と`hw`を付けた`app_started`で確認した。応答は`accepted: 1`）。受け側が`hw`を保存するかどうかは受け側の実装による。
- 環境変数`VRCT_TELEMETRY_URL`は、開発者が自分のPCに立てた代わりの受け側を指すためのもので、ループバックのHTTPのアドレスだけを受け付ける。ほかの値は無視する。
- 受け側は送信元のIPアドレスや端末の識別子を保存しない設計である（受け側の担当の説明による）。通信の相手として、Cloudflareは送信元のアドレスを扱う。
- 受け側は通知ごとに、受信した時刻と接続元の国を記録する。国はクライアントが送る値ではなく、Cloudflareが接続元のアドレスから出す値である（2026-11-14に受け側の読み取り用のビューで確認した）。利用者に見せる説明にもこの2つを含める。

### LLMでの翻訳

Plamo、Gemini、OpenAI、Groq、OpenRouter、OpenAI互換、LM Studio、Ollamaは、現在の翻訳対象の本文、言語の指定、プロンプトと直近の会話履歴を接続先へ送る。プロンプトにはシステム向けの指示と対応言語も含む。SDKはOS・CPUアーキテクチャ・Pythonやパッケージのバージョンなどの情報をヘッダー等で送る。具体的な項目はSDKによって異なる。LM StudioとOpenAI互換では設定したURLが送信先になり、OpenRouterでは選んだモデルの提供元にも処理が渡る。

付属の`src-python/models/translation/translation_settings/prompt/translation_*.yml`は、`history.use_history: true`でチャット・マイク・スピーカーの履歴を有効にしている。直近の最大5件を、時刻と入力元を付けて含め、整形後の履歴は最大4,000文字に制限する。OCRの過去の履歴は既定では含めないが、今回の翻訳対象がOCRの本文なら送る。これらはプロンプトファイルの`use_history`、`sources`、`max_messages`、`max_chars`で決まり、履歴専用のUIスイッチはない。DeepLとCTranslate2はこの履歴を送らない。

翻訳用履歴はメモリー内に最大20件保持し、同じ送信先を使い続ける間だけ引き継ぐ。[同意と外部への送信](cross-cutting.md#同意と外部への送信)に従い、エンジン・URL・モデルの変更で履歴の世代を更新する。翻訳のオン・オフ、タブ、翻訳用APIキー、CTranslate2の重み、選択していないエンジンのURLやモデルを変えた場合も、誤送信を防ぐために無効にする。同じ値の再保存では無効にしない。世代を戻す処理はなく、送信先を切り替えて戻っても古い履歴は再利用しない。

各メッセージは受付時の世代を保持し、処理中に設定が変わった場合は履歴の利用と追加を省く。要求ごとに履歴とクライアントの参照を固定し、空の履歴も明示的に渡す。既に始まった要求は、それまでの接続先への送信が続く場合がある。設定を変えても送信済みの情報は取り消せない。履歴の無効化は翻訳用の一時バッファだけに作用し、画面やファイルの会話ログは変えない。

## ローカルの音声サーバー

| 相手 | 起動 | 通信 |
|---|---|---|
| 同梱のspeech.cpp（TTS、ASR） | `build/vrct-vc-worker … speech-server`。プロファイルは`japanese`、`multilingual`、`asr` | OSが割り当てた`127.0.0.1`のポート。`GET /health`、`GET /v1/models`で準備を確かめる。起動の待ち時間は120秒 |
| 外部のspeech.cpp | 利用者が起動する | ループバックの`http`だけを受け付ける |
| 読み上げ | — | `POST /v1/audio/speech`に`{input, voice, language, response_format: "pcm", seed?, instructions?}`。応答は`audio/pcm`。4000文字まで |
| 音声認識（REST） | — | `POST /v1/audio/transcriptions` |
| リアルタイム音声認識 | — | `ws://…/v1/realtime`。`session.update`と`input_audio_buffer.append`、`commit`、`clear` |
| 話者分離（任意） | `asr`プロファイルに話者分離モデルのパスがあれば、同じサーバーに3つ目のモデルとして読み込ませる | `/v1/models`がCPU以外の装置にある`diarization`を返すサーバーへのスピーカーの接続だけが、`session.update`の`audio.input.diarization`に`{}`を入れる。確定した発話の`speakers`（ラベル、開始、終了）を受け取る。マイクの接続は要求しない |
| RVCワーカー | `build/vrct-vc-worker … rvc …` | stdin・stdoutでPCM（48kHz、3840フレーム単位）。制御はJSON行（32KiBまで） |

同梱TTSサーバーの停止・異常終了は、起動ごとの識別子と、その実行を使うTTSの世代を照合して処理する。現在のTTSが使うサーバーが終了したときは、TTSをオフにして待機中・再生中の読み上げを取り消し、従来どおり音声の状態取得でUIに伝える。同じ実行の停止直後と後処理後に通知が重なっても、無効化とTTSの世代更新は一度だけ行う。古い実行からの遅れた通知で、別の接続先や新しいサーバー実行を使うTTSをオフにしない。

同梱ASRサーバーは認識モデルとVADモデルを必ず読み込み、設定に話者分離モデルのパスがあるときだけそれも読み込む。起動の確認では`/v1/models`の内容を設定と照合する。話者分離モデルを指定したのにサーバーがそれを持たないとき、指定していないのに持つときは、`speech_server_model_tasks`で起動を失敗にする。

同梱ASRサーバーも、起動ごとの識別子とマイク・スピーカーそれぞれの収録世代を照合する。終了した実行を使う収録だけを停止し、同じ終了通知を重ねて処理しない。古い実行の通知で新しい収録を止めない。異常終了で停止した場合は、従来どおり原因を通知する。

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

### WebviewのContent Security Policy（CSP）

`src-tauri/tauri.conf.json`の`app.security.csp`を、上記3ウィンドウの配布用HTMLに共通で適用する。Tauri CLI 2.12.4の`node_modules/@tauri-apps/cli/config.schema.json`にあるdirective map形式を使う（Rust側はTauri 2.12.5）。ブラウザーから読み込む資源の許可であり、Rust/Pythonの通信やTauri capabilityの代わりではない。

| Directive | 許可するsource | 根拠 |
|---|---|---|
| `default-src`、`script-src` | `'self'` | Viteが生成する同一オリジンのJS、共有chunk、modulepreload。i18nextとjs-yamlは同梱された翻訳データを処理する。eval、Functionコンストラクター、Wasmは使わない |
| `style-src` | `'self'`と下記2つのSHA-256 | CSS Modules/SCSSから生成したCSSと、依存が実行時に挿入する固定の`<style>`だけ |
| `style-src-attr` | `'none'` | HTMLのstyle属性や`setAttribute("style", …)`は許可しない。Reactの`style` prop、virtua、色選択、倍率・フォント・OCR領域の更新はCSSOMのプロパティ代入を使う |
| `img-src` | `'self' data:` | 同梱PNG/SVG、Viteがインライン化した小画像、選択欄とreact-colorfulのdata SVG。SVGの`?react` importはJS内の要素になる |
| `font-src` | `'self'` | OSにある選択フォントとNoto/systemのフォールバック。現在はフォントファイルの取得も`@font-face`もない。リモートフォントは使わない |
| `connect-src` | `'self' ipc: http://ipc.localhost https://ipc.localhost` | 同一オリジンのmodulepreloadのfetchとTauri IPC。WindowsのHTTP/HTTPS形式も含む。pluginコマンドも同じIPCを通る |
| `media-src`、`worker-src`、`frame-src`、`object-src` | `'none'` | UIに音声・動画プレイヤー、Worker、iframe、objectはない |
| `base-uri` | `'self'` | 別オリジンへの基準URLの変更を禁止 |
| `frame-ancestors`、`form-action` | `'none'` | 埋め込みとHTMLフォームによる送信を禁止 |

`style-src`に加える固定値は、react-colorful 5.6.1の`'sha256-I2px+fnpbN4E5+Djrj7aoTIyq9yyREkuVl19f4Sye9A='`と、react-toastify 11.0.5の`'sha256-Xo8/tnRnpUxMw05nUf764oT49W2GEbQN9LaX8Wqxuwg='`。依存が実際に挿入するCSS文字列のUTF-8バイトから計算する。配布用に`'unsafe-inline'`、`'unsafe-eval'`、`'wasm-unsafe-eval'`を許可しない。依存を更新して文字列が変わったら、挿入方法とCSS内のURLを確認したうえでハッシュを更新する。

`dangerousDisableAssetCspModification`は既定の`false`を保つ。TauriによるHTMLのnonce/hash挿入を無効化しない。`script-src-elem`を別に指定してTauriの`script-src`への追加を無効にすることもしない。`freezePrototype`は別のprototype汚染対策であり、CSPを有効にする条件ではない。今回は既定の`false`を保つ。

Python sidecarはshell pluginのstdin/stdoutでつなぐ。UIはPythonのHTTPサーバー、OBS、会話配信用WebSocket、音声サーバーに直接接続しないため、それらのホストやポートを`connect-src`に加えない。OBS用URLはコピーする文字列であり、Tauri内でページを表示しない。モデル取得は同意後にPython側で実行する。モデルカード、ライセンス、Aboutの外部リンクはopenerまたは既存のPython側の処理へ渡す。ログの保存もPython側で行う。OCR領域のプレビューはCSSの矩形であり、画面キャプチャ画像を読み込まない。`blob:`、`asset:`、`http://asset.localhost`の許可は不要で、asset protocolも無効のままとする。

`devCsp`だけはViteのReact Refresh用inline script、HMR用style、および`ws://localhost:1420`、`ws://127.0.0.1:1420`、`ws://localhost:1421`、`ws://127.0.0.1:1421`を許す。通常のdev URLは`http://localhost:1420`。`TAURI_DEV_HOST`に別のホストを指定する場合は、開発用のローカルTauri設定で`devCsp.connect-src`にそのホストのHMR URL（ポート1421）を明記する。配布用CSPを広げない。

静的検査は`src-ui/logics/common/contentSecurityPolicy.test.js`にある。設定、ソースの危険な呼び出しと資源の読み込み、依存のCSSハッシュを検査する。`dist/`があれば、生成JSにeval/Wasm/Workerがないこと、生成CSS/HTMLが同梱資源だけを参照すること、生成JS内のCSSも同じハッシュになることを追加で確かめる。`dist/`がない場合は生成物の検査だけをスキップするため、Viteビルド後にも単独で実行する。静的検査は任意の動的URLのデータフローやWebview実装の挙動までは証明しない。[配布ビルドでのCSP検証](../readme_build.md#配布ビルドでのcsp検証)を別途実行する。

### Tauriのコマンド

| コマンド | 呼べるウィンドウ | 働き |
|---|---|---|
| `get_font_list` | `main` | システムのフォント名の一覧 |
| `set_vr_panel_window` | `main` | VRパネルのウィンドウを作る・消す。Linuxでは、作ったウィンドウを表示せず、中のページをデスクトップに出ない場所へ移してバックエンドへ渡す（[VR画面の受け渡し](use-cases.md)） |
| `main_window_restore` | `main` | 最小化したメイン画面を戻して前面に出す。Waylandでは最小化の状態をアプリが知れず、ポータルのホットキーには前面に出す権利もないため、UIが最小化したことを覚えておき、戻すときはKWinに頼む |
| `quick_chat_show`、`quick_chat_configure`、`quick_chat_take`、`quick_chat_finish`、`quick_chat_shortcut_platform` | `main` | 小窓を開く、設定を渡す、送信要求を受け取る、結果を返す、ホットキーの登録方法を調べる |
| `quick_chat_context`、`quick_chat_submit`、`quick_chat_hide` | `quick_chat` | 設定を読む、送信を頼む、隠す |
| `portal_shortcuts_bind` | `main` | Waylandでホットキーを登録する（180秒で打ち切り） |
| `screencast_support` | `main` | `{supported, active}`。ウィンドウを共有できるデスクトップか（LinuxのWaylandセッション）、いま共有中か。何も始めない |
| `screencast_start` | `main` | デスクトップにウィンドウの共有を頼む（[ウィンドウの共有](#ウィンドウの共有linux)）。引数は保存済みの`restoreToken`（なければ`null`）。成功すると`{restore_token}`を返す。共有中に呼ぶと、前の共有を終えてから頼む。選択画面の待ち時間は180秒 |
| `screencast_stop` | `main` | 共有を終え、ヘルパーを止め、ポータルのセッションを閉じる |

Quick Chatのコンテキストは、`ready`、`language`、`enter_to_send`、`clear_on_send`に加え、保存済みの`ui_scaling`（整数、40〜200%）と`font_family`（空白だけではなく、制御文字を含まない256文字以内のローカルフォント名）を持つ。Rustは呼び出し元と値を検証してから置き換える。新しい2項目を省略した要求は100%と`Yu Gothic UI`を使う。小窓はフォント名をCSSの文字列として扱い、既存のNoto／システムフォントへのフォールバックを保つ。設定ファイルのキーやPython側のIPC形式は変更しない。

VRパネルの要求は`main`が中継する（セキュリティ監査 SEC-02）。中継するのは、VRパネルが実際に送る操作として`VR_PANEL_RELAY_PATHS`（`src-ui/logics/common/vrPanelWire.js`）に載せたものだけで、載っていない操作は新しいエンドポイントも含めて中継しない。載せているのは、VRパネル自身の窓と操作バー、ランチャーの4つのスイッチ、言語の窓、VRの設定の窓が変える設定（デバイスとしきい値、翻訳・音声認識・チャット読み取りの選択、メッセージの変換、VRの字幕、表示言語とフォント）である。アプリの終了と更新、ファイルを開く操作、モデルや実行環境の取得、認証キーとトークン、接続先（URL、WebSocket・OBS・OSCのホストとポート、証明書）、音声の設定、テレメトリの有効化と同意は載せない。`main`は中継する要求に`"origin": "vr_panel"`を付け、バックエンドも同じ一覧（`src-python/models/vr_panel_policy.py`）で確かめる。一覧にない要求は解釈せず、403と`vr_panel_request_refused`を返す。`origin`のない要求は`main`自身のもので、`vr_panel`以外の`origin`は拒否する。2つの一覧が同じことは試験で確かめる。`vr-panel-stdout`のイベントを送れるのは、イベントの送信権限を持つ`main`と`vr_panel`のウィンドウだけである（`src-tauri/capabilities`）。VRパネルへ写す状態にも、認証キーとトークンは入れない（[VRパネルへ写す状態](#vrパネルへ写す状態)）。ウィンドウの共有を戻すトークン（`ocr_portal_restore_token`）も、中継と写しの対象から外す。

### ウィンドウ間の連携

| イベント | 向き | 内容 |
|---|---|---|
| `quick-chat-requested` | Rust → `main` | 小窓から送信の要求が来た。`main`は`quick_chat_take`で受け取り、`/run/send_message_box`で送る |
| `quick-chat-result` | Rust → `quick_chat` | `{id, accepted}`。同じIDの再送には前の結果を返す |
| `quick-chat-opened` | Rust → `quick_chat` | 入力欄にフォーカスを戻す |
| `quick-chat-context-changed` | Rust → `quick_chat` | 設定が更新された。ペイロードは使わず、`quick_chat_context`で検証済みの設定を読み直す。フォーカスは移動しない |
| `portal-shortcut` | Rust → `main` | Waylandでホットキーが押された |
| `vr-panel-ready` | `vr_panel` → `main` | VRパネルの準備ができた。`main`は状態を送り直す |
| `vr-panel-stdout` | `vr_panel` → `main` | VRパネルからの要求。`main`が許可したものだけをサイドカーへ渡す |
| `vr-panel-config-page` | `vr_panel` → `main` | VR内の設定を開いた・閉じた |
| `vr-panel-pointer` | `main` → 全体 | VR内のポインタの位置 |

#### VRパネルへ写す状態

画面の状態は、イベントではなくVRパネルが開いたチャンネルで送る（セキュリティ監査 SEC-03、`src-tauri/src/vr_panel_state.rs`）。状態には会話ログが入る。イベントは聞く権限を持つほかのウィンドウ（字幕のオーバーレイとQuick Chat）にも届き、宛先を指定したイベントも、宛先を限らずに聞いているリスナーには届く。チャンネルのメッセージは、それを開いたウェブビューにだけ届く。

- VRパネルは起動すると`vr_panel_state_subscribe`にチャンネルを渡し、受け付けられたら`vr-panel-ready`を送る。受け付けるのは`vr_panel`のウィンドウからの呼び出しだけで、開き直したパネルのチャンネルが前のものに替わる。
- `main`は`vr_panel_state_push`で状態を送る。受け付けるのは`main`からの呼び出しだけ。購読しているパネルがなければ`false`を返し、次の会話ログは全件で送る。パネルのウィンドウを閉じるとチャンネルを捨てる。
- 送るのは、VRパネルの画面が読む状態だけ（`src-ui/logics/common/vrPanelWire.js`の`vrPanelStateNames`）。設定は、VRパネルが丸ごと読むカテゴリ（表示、デバイス、翻訳、音声認識、チャット読み取り、VR、その他）のもの。そのほかは会話ログ、ランチャーと言語の窓の状態、メーター、入力と出力の表示など、名前で挙げたatomだけ。高度な設定（WebSocket、OBS、OSC、テレメトリ）、更新、ホットキーは送らない。認証キーとトークンは、カテゴリに入っていても送らない。VRパネルのコードが新しいatomを読むようになると、ソースを読む試験（`src-ui/logics/test/vrPanelStateScan.js`）が一覧に足すまで失敗する。
- 会話ログだけは前に送ったログとの差分で送る。通し番号が合わなければ、VRパネルが`vr-panel-ready`で全件を頼み直す。

VRパネルで会話ログを閉じている間も、状態の受信とログの更新は続ける。閉じた領域は描画せず、操作も受け付けない。ログ本体の購読を外し、開き直すと保存した表示位置と末尾への追従状態を戻す。上へスクロールして読んでいた場合はその位置を保ち、それ以外は最新の末尾に追従する。保存中に古い行が保持上限を超えた場合は、通常のログ更新と同じように位置を補正する。

レーザーの位置は最後の`vr-panel-pointer`を保持し、パネル内のスクロール、表示内容の差し替え、レイアウトの変更でもホバー対象を調べ直す。判定は1フレームに1回にまとめ、対象が変わらなければ`data-vr-hover`を書き換えない。ポインタがなくなったらホバー表示を解除する。

### ウィンドウの共有（Linux）

チャット読み取りのために、利用者が選んだウィンドウ1つの映像を受け取る（[UC-05](use-cases.md)）。`screencast_start`を呼ぶのは、次の2つのときだけである。利用者が設定ページのボタンを押したとき。利用者がチャット読み取りをオンにし、読み取れるウィンドウが名前で見つからず、前に共有したウィンドウをデスクトップが覚えているとき（UC-05の「オンにしたときの共有のやり直し」）。起動時には呼ばない。

| 相手 | やりとり |
|---|---|
| XDG ScreenCast portal（`org.freedesktop.portal.ScreenCast`） | Tauriが専用のD-Bus接続で、アプリIDの登録、`CreateSession`、`SelectSources`、`Start`、`OpenPipeWireRemote`の順に呼ぶ。`SelectSources`にはウィンドウだけ（`types: 2`）、1つだけ（`multiple: false`）、ポインターを映さない（`cursor_mode: 1`、対応しているとき）、選んだ結果を覚える（`persist_mode: 2`、ポータルの版が4以上のとき）、保存済みの`restore_token`を渡す。ポータルの応答が1（取り消し）なら`portal_cancelled`、そのほかの失敗は`portal_request_failed`、ウィンドウの共有に対応していなければ`screencast_unsupported` |
| `vrct-screen-capture`（`native/screen-capture`） | Tauriが`OpenPipeWireRemote`の接続を標準入力として渡して起動する。引数は親のプロセスID、PipeWireのノードID、フレームファイルの場所、間隔（250ミリ秒）。メモリーのバッファーだけを受け付け（DMA-BUFは使わない）、形式はBGRx、BGRA、RGBx、RGBA。デスクトップには最大で毎秒4枚を頼み、明らかに早く届いた分は捨てる。標準出力のパイプをTauriが閉じるか、Tauriが終了すると止まる。標準エラーに`streaming`と、止まった理由（`screen_capture_<理由>`）を1行ずつ出す |
| フレームファイル | `$XDG_RUNTIME_DIR/vrct-vox/vr-panel-<pid>/screen-frame`（ディレクトリは0700、ファイルは0600）。先頭64バイトはリトルエンディアンで、目印`VRCTSCR1`、通し番号（書き換え中は奇数）、識別番号（共有が終わると0。上位32ビットはヘルパーのプロセスID）、幅、高さ、1行のバイト数、画素の並び（0: BGRx、1: BGRA、2: RGBx、3: RGBA）、フレームの時刻。続けて画素を置く。最後の行は幅×4バイトだけを持つ。バックエンドは通し番号が読む前後で同じ偶数のときだけ使い、ファイルがない、識別番号が0、ヘルパーのプロセスがない、のどれかなら共有は終わったとみなす |

変化のないウィンドウは新しいフレームを送らないので、フレームが古いことだけでは共有の終わりと判断しない。

| イベント | 向き | 内容 |
|---|---|---|
| `screencast-ended` | Rust → `main` | アプリが止めたのではない共有の終わり。`{reason}`は`ended`（ウィンドウが閉じた、デスクトップ側で共有を止めた）か`failed`（ヘルパーやポータルが止まった）。`main`は共有の表示を戻し、お知らせを出す |

`RunEvent::Exit`で共有を終える。ヘルパーは親が消えたときにも止まるので、アプリが強制終了しても残らない。

### ホットキー

- 動作は9つ: 小窓を開く、VRCT-VOXの最小化と再表示、翻訳・マイク・スピーカーのオンオフ、読み上げの停止、音声のミュートと再開、TTSとRVCのオンオフ。既定ではどれも割り当てない。
- 読み上げの停止、ミュート、TTS、RVCのホットキーは、メイン画面の同じボタンとスイッチを押したのと同じ処理を通る。押した時点の状態で判断し、同じ確認とお知らせが出る。ミュート中に経路の準備ができていなければ、再開はしない。
- X11とXWaylandではTauriのグローバルショートカット、ネイティブのWaylandではXDG GlobalShortcuts portalで登録する。KDEでは設定したキーをデスクトップ側にも反映し、反映できなかったときはお知らせを出す。
- 設定画面を開いている間と、サイドカーの準備ができるまでは無効にする。

### 権限

`src-tauri/capabilities/`で、`main`にウィンドウ操作、ショートカット、ファイル、GitHubへのHTTP、サイドカーの起動を許す。`quick_chat`にはイベントの受信だけを許し、コマンドは呼び出し元のウィンドウ名をRust側で確かめる。
