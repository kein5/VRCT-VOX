# データ形式と保存

IPCでやり取りする主なデータの形と、ディスクに残すファイル。設定キーの一覧は[設定キー一覧](reference/config-keys.md)（生成）にある。

## 主なデータの形

### 言語の組（タブごと）

`selected_your_languages`と`selected_target_languages`。タブ番号`"1"`〜`"3"`ごとに、枠番号から言語への辞書を持つ。

```json
{
  "1": {"1": {"language": "Japanese", "country": "Japan", "enable": true}},
  "2": {"1": {"language": "Japanese", "country": "Japan", "enable": true}},
  "3": {"1": {"language": "Japanese", "country": "Japan", "enable": true}}
}
```

- `language`と`country`は英語の識別子であり、保存・IPC・OSC・プリセットでは翻訳しない。`selectable_language_list`も`[{"language": "Japanese", "country": "Japan"}, …]`のまま。UI表示用のタグと表示名はUI内で解決し、選択のペイロードには加えない（[国際化](cross-cutting.md#国際化)）。
- 自分の言語は枠`"1"`だけ、相手の言語は枠`"1"`〜`"3"`を持つ。既定で有効なのは相手の言語の枠`"1"`だけである。
- 更新には全タブと全枠、および各枠の`language`・`country`・`enable`が必要である。空の辞書、不足・余分なキー、辞書でない入れ子は、変更や保存をせず400の`VALIDATION_CONFIG_VALUE_INVALID`で拒否し、`data`に元の値を返す。翻訳エンジンの辞書も全タブと文字列の値を必要とする。
- `language`と`country`は`transcription_lang`にある組だけを受け付ける。無効な枠は元の値に戻る（エラーにはしない）。
- 入れ替え（`/run/swap_your_language_and_target_language`）は、両方の辞書を検証してから設定ロック内でまとめて変更し、最終的な言語の組で翻訳エンジンを1回だけ調整する。保存も片側だけの状態を取得しない。両方向に対応する選択済みのエンジンは保持し、`{"your": …, "target": …}`を返す。
- 選択中のタブは`selected_tab_no`（`"1"`、`"2"`、`"3"`）、タブごとの翻訳エンジンは`selected_translation_engines`（`{"1": "CTranslate2", …}`）。

### 音声認識エンジンの選択

`SELECTED_TRANSCRIPTION_ENGINE`は既存のエンジン名の文字列、または未選択を表す`null`を保存する。新規設定でキーがない場合の既定値は`null`。保存済みの`Google`など正常な選択はそのまま読み込み、再同意は求めない。今回保存する`null`も再起動後に未選択として保持する。不正な型・未知のエンジン名は読み込まず未選択の既定値を保つ。空文字列や新しいエンジン識別子への置換は行わない。

キー名と`/get/data/selected_transcription_engine`、`/set/data/selected_transcription_engine`は維持する。取得応答には未選択なら`null`、選択済みなら従来の文字列を返す。選択の更新要求は従来のエンジン名を使い、不正な値は`VALIDATION_CONFIG_VALUE_INVALID`で拒否する。可用性やAPIキーの削除で選択を上書きしない。

従来の文字起こしの有効化で未選択なら400の`TRANSCRIPTION_ENGINE_NOT_SELECTED`と`data: false`を返す。重みの欠落・検証失敗とAPI認識器の構築失敗は、それぞれ`TRANSCRIPTION_MODEL_MISSING`と`TRANSCRIPTION_ENGINE_UNAVAILABLE`を`/set/enable/transcription_send`または`/set/enable/transcription_receive`の400通知で知らせ、開始要求の結果は従来どおり`false`となる。初回選択画面の継続操作はUI内の一時状態で、設定には保存せず、キャンセル・画面の破棄で捨てる。[同意の規則](cross-cutting.md#同意と外部への送信)を参照する。

### 音声認識の数値設定

マイクとスピーカーの`avg_logprob`は−2以上0以下、`no_speech_prob`は0以上1以下の有限の数値を受け付ける。IPCでは数値に変換できる文字列も受け付ける。`NaN`・無限大、範囲外、真偽値などは変更や保存をせず400の`VALIDATION_CONFIG_VALUE_INVALID`で拒否し、`data`に元の値を返す。保存済みの不正な値は読み込み時に既定値へ戻す。

`MIC_`と`SPEAKER_`の整数設定は、保存値の読み込みと設定プロパティへの代入で次の範囲を検証する。`null`、真偽値、小数、文字列は受け付けない。IPCで整数に変換する従来の処理は維持し、範囲外の値には既存の`VALIDATION_MIC_*`・`VALIDATION_SPEAKER_*`と元の値を返す。

| 設定名の末尾 | 範囲 |
|---|---|
| `THRESHOLD` | 0〜2000 |
| `RECORD_TIMEOUT`、`PHRASE_TIMEOUT` | 0〜30秒。`RECORD_TIMEOUT`は`PHRASE_TIMEOUT`以下 |
| `MAX_PHRASES` | マイクは0〜30、スピーカーは0〜60 |
| `NO_REPEAT_NGRAM_SIZE` | 0以上 |

保存したタイムアウトはJSONのキー順に関係なく、組として検証する。範囲外や型が不正な値は既定値へ戻す。範囲内でも記録時間がフレーズ時間を超える組は、両方を既定の3秒へ戻す。

### 計算デバイスと計算型

翻訳と文字起こしの`SELECTED_*_COMPUTE_DEVICE`は、`device`・`device_index`・`device_name`で現在の一覧と照合する。保存した`compute_types`は識別に使わず、現在の一覧の値へ更新する。対応する計算型が増減しただけでは、選択したGPUを変更しない。

`SELECTED_*_COMPUTE_TYPE`は、JSONのキー順に関係なく保存したデバイスの現在の対応型で検証する。対応していれば`float16`などの選択を保つ。デバイスが見つからなければ既定のCPUを使い、対応しない計算型は既定の`auto`へ戻す。実行中の計算型の変更は、その時点で選択しているデバイスで検証する。

### ネットワーク設定

`OSC_PORT`、`WEBSOCKET_PORT`、`OBS_BROWSER_SOURCE_PORT`は、保存値もIPCの変更要求も整数型の1〜65535だけを受け付ける。真偽値、小数、文字列（`"80"`を含む）、0、負数、65536以上、nullは拒否する。保存値が不正なら、その設定の既定値（順に9000、2231、2232）を保ち、読み込み後の保存で書き直す。UIは1〜65535の数字入力を整数にして送る。空欄での保存は不正値として扱う。

変更要求が不正なら、設定の保存や稼働中サービスの停止に進まず、元の値を`data`に入れて400を返す。エラーコードは順に`VALIDATION_OSC_PORT_INVALID`、`WEBSOCKET_PORT_INVALID`、`OBS_BROWSER_SOURCE_PORT_INVALID`。WebSocketとOBSは新しいポートで起動できてから値を保存し、失敗時は元のポートで復旧を試みる。

`WEBSOCKET_HOST`はIPv4アドレスの文字列だけを受け付け、`0.0.0.0`、IPv6、ホスト名、文字列以外は拒否する。不正な保存値は既定の`127.0.0.1`へ戻す。変更要求は`VALIDATION_INVALID_IP`で拒否し、元のホストとサービスを保つ。OBSもこのホストを使う。

`WEBSOCKET_AUTH_TOKEN`は空でない文字列を保存する。null、空文字列、空白だけの文字列、文字列以外の保存値は読み込まず、起動時に生成した新しい秘密値を通常の既定値と同じ処理で保存する。正常な保存値は変えない。設定画面がコピーするWebSocket・OBSのURL、OBSのHTML、WebSocketの認証には同じ設定値を使う。修復された場合は外部アプリのURLをコピーし直す必要がある。設定キー名とIPCエンドポイント名は変えず、別キーへの移行は行わない。

`LMSTUDIO_URL`、`OPENAI_COMPATIBLE_URL`、`TRANSCRIPTION_CUSTOM_URL`は、保存値の読み込み時と変更要求の受付時に同じ規則で検証する。HTTPSは任意のホストを受け付ける。HTTPは`localhost`、127.0.0.0/8、::1、10/8、172.16/12、192.168/16、fc00::/7、IPv4・IPv6のリンクローカルに限る。LANのホスト名をDNSで解決してHTTPを許可することはない。URLのユーザー情報、キー・トークン・パスワード・認証情報・署名などを表すクエリ名、フラグメント、不正なポートは拒否する。

HTTPでプライベートLANやリンクローカルのアドレスへ接続する場合は、文章・音声・APIキーが暗号化されない旨を設定欄に表示する。同じPC内で通信するループバックには、この警告を出さない。URLは保存時に検証し、APIキーを入力して保存すると接続先へ送って認証する旨を、すべてのカスタムURLに表示する。URLの入力中は通信しない。OpenAI互換とCustom WhisperのURL単独の変更は、キーが保存済みなら通信せず`CREDENTIAL_REENTRY_REQUIRED`で拒否する。同じURLの再保存は通信も変更もせず成功し、キーが未設定ならURLだけを保存する。URLとキーを一緒に保存するときは入力した組み合わせで接続先を確かめる（[APIキーの変更](cross-cutting.md#apiキーの変更)）。URLの検証で拒否した変更は、既存の`CONNECTION_LMSTUDIO_URL_INVALID`、`CONNECTION_OPENAI_COMPATIBLE_URL_INVALID`、`CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID`を返して元のURLを保つ。

不正な保存済みURLは空文字列にして接続を止め、起動完了時に対応するURLエラーで再設定を促す。この通知は表示時のUI言語で翻訳し、保存済みの言語が後から反映された場合も表示を更新する。保存済みキーを別の既定ホストへ送らないため、既定URLには戻さない。キー自体は残す。空文字列は未設定の状態として保存できる。キー名・IPCエンドポイント名・JSONの形式は変更しない。

### メッセージ

送信したメッセージ、マイクとスピーカーの認識結果、OCRで読んだ文に共通の形。

```json
{
  "id": "4b1c…",
  "original": {"message": "こんにちは", "transliteration": []},
  "translations": [{"message": "Hello", "transliteration": []}],
  "source": "ocr"
}
```

| 項目 | 内容 |
|---|---|
| `id` | 入力欄から送ったときはUIが付けたUUID。マイクとスピーカーではUIが受け取ってから付ける。OCRは`transcription-ocr-<番号>` |
| `original` | 元の文と、ひらがな・ローマ字の読み（`[{orig, hira?, hepburn?}]`、オフなら空配列） |
| `translations` | 有効な相手の言語の順に並んだ訳。翻訳がオフ、または空のメッセージでは空配列 |
| `source` | OCRのときだけ`"ocr"` |
| `output_failures` | 出力の一部が例外になったときの`[{output, error_code: "MESSAGE_OUTPUT_FAILED"}]`。同期の戻り値には全出力後の一覧を含める。通常は省略 |
| `delivery_reason` | 自分のメッセージ（入力欄とマイク）を、「VRChatにメッセージを送信する」がオフのためチャットボックスへ送らなかったときだけ`"vrchat_off"`。ほかの出力は行う。UIは行の状態を`ok`のまま、「送信」の代わりに「VRChatには未送信（設定でオフ）」と表示する。相手の発言（スピーカー、OCR）には付けない |

- 入力欄からは`/run/send_message_box`に`{"id", "message"}`を送り、応答で上の形を受け取る。UIは送る前に行を「送信中」として出し、200の応答で送信中を解除する。同じ行のIDと時刻を保ち、応答の`original`と`translations`に読みも含めて更新する。Quick Chatからの送信とVRパネルに映す行も同じ処理を使う。デスクトップでは待機中のアイコンが回転し、VRパネルでは動かない文言で示す。
- 通信失敗、400・404・423・500の応答、バックエンドの停止では、該当する送信中の行を`status: "failed"`にし、本文を残して「送信を確認できません」と表示する。自動では再送しない。エラー応答にIDがない場合は送信中の全行を対象にする。その後にID付きの200が届けば、その行の状態、読みを含む原文と訳を更新する。
- 各出力の失敗は、別の400通知`/run/message_output_error`でも知らせる。`result.data`は`{id, source, output, error_code}`で、`id`がない入力では`null`。`source`は`chat`・`mic`・`speaker`・`ocr`、`output`は`osc`・`overlay_small`・`overlay_large`・`clipboard`・`ui`・`websocket`・`logger`・`history`・`tts`のいずれか。本文や例外の詳細は入れない。UIへの通常通知の後に失敗する出力もあるため、全入力元の失敗通知をこの経路で扱う。送信行を失敗扱いにせず、出力先ごとに警告を表示する。
- マイクは`/run/transcription_send_mic_message`、スピーカーは`/run/transcription_receive_speaker_message`、OCRは`/run/transcription_ocr_message`で届く。

### リアルタイム字幕と配送結果

リアルタイム音声認識は200の`/run/realtime_caption`で通知する。行は`source`（`mic`・`speaker`）、`generation`、`namespace`、`item_id`の組で識別する。`revision`は同じ行の更新番号である。

`partial`は認識途中、`final`は認識の確定であり、どちらも配送完了ではない。`text`に認識文、`translations`に訳の配列を持つ。`translated`は原文の読みを含む`original`と`translations`を更新するが、配送の待機は解除しない。`discarded`は空の確定結果や、表示前に期限が切れた字幕を退役させる。

`speakers`は、その発話で話した人のラベルの配列である（`["A"]`、`["A", "B"]`）。サーバーが話者分離モデルを持つときの、スピーカーの`final`と`translated`だけが値を持つ。`partial`とマイクの行、話者分離をしないときは空の配列である。ラベルは大文字1〜3字で最大4個、話しはじめた順に並ぶ。0.4秒以上話した声を数え、どの声もそれに満たなければ最も長い声を1つ入れる。ラベルは1つのセッションの中で声を区別する記号であり、人の名前ではない。セッションが変わると振り直される。話者分離の推定は誤ることがある。行は`speakers`として保持し、ログでは状態の表示の隣に「話者A・B」と出す。

表示した空でない`final`には、次の結果通知を1回発行する。`revision`は`final`より2大きい。本文と訳はこの通知に含めず、同じ行に保持する。

```json
{"status": 200, "endpoint": "/run/realtime_caption", "result": {
  "source": "mic", "generation": 4, "namespace": "session", "item_id": "utterance",
  "revision": 3, "state": "outcome", "outcome": "not_delivered", "reason": "expired"
}}
```

| `outcome` | `reason` | 行の状態と意味 |
|---|---|---|
| `delivered` | `null` | `status: "ok"`。適用対象の出力処理を終えた、または中断前に少なくとも1つの出力先へ配送した。マイクは「送信」、スピーカーは「受信」。全出力先への配送、VRChatでの受信確認、TTSの再生完了は意味しない |
| `delivered` | `vrchat_off` | `status: "ok"`。マイクの行だけ。「VRChatにメッセージを送信する」がオフのため、チャットボックスへは送らなかった。ほかの出力は行った。「VRChatには未送信（設定でオフ）」と表示し、警告の色は使わない |
| `not_delivered` | `expired`・`revoked`・`superseded`・`filtered` | `status: "not_sent"`。出力の成功を記録する前に、2秒の期限切れ、配送世代やセッションの失効、チャットボックスの順序制御、ワードフィルターで配送を省略した。処理失敗とは区別する |
| `failed` | `processing_failed`・`queue_full` | `status: "failed"`。処理自体の例外・VRAM不足、または確定結果の待ち行列が満杯。本文を残す |

出力先だけの例外では`delivered`を維持し、既存の`MESSAGE_OUTPUT_FAILED`警告を使う。行に警告を重ねない。OSC、WebSocket、クリップボード、会話ログ、読み上げの受付が成功したら、次の出力先で待つ前に記録する。以後に期限切れ・失効・処理失敗が起きても、その行は`delivered`にする。OSCが順序制御で省略されても、他の出力先への配送に成功した行は同じ扱いにする。既に終えた出力は取り消さず、自動で再送しない。

認識が確定した行は`status: "pending"`で始める。デスクトップのマイク行は「送信中…」と待機アイコン、スピーカー行は「処理中…」を使う。VRパネルは同じ行を映し、待機アイコンを動かさず文言で示す。処理失敗のマイク行は既存の「送信を確認できません」、スピーカー行は「処理に失敗しました」と表示する。送信を省略したマイク行は理由を添え、スピーカー行は「処理を中止しました」と表示する。

待ち行列で期限が切れた結果も、停止・ミュート・終了で処理へ進めなかった結果も、表示済みなら結果通知を出す。読取ワーカーが既存の待機周期で期限と配送世代を確認するため、翻訳の終了を待たずに行を確定できる。ただし、まだ出力の成功がなく、最初の出力処理が実行中なら、その成否が戻るまで確定を待つ。この待機は停止要求を妨げず、残りの出力を許可することもない。表示しなかった確定結果には出さない。停止後や新しいセッションの開始後でも、UIに残っている同じIDの確定行だけを更新する。未知・削除済み・認識途中の行には適用せず、一度確定した結果は後続の通知で変えない。

結果を受け取る前にサイドカーとの接続が終了した場合は、UIが未確定の行を`failed`にする。この場合だけはバックエンドの結果通知ではなく、配送を確認できない状態として扱う。認識途中の行は消し、受信済みの結果は変えない。入力欄の送信エラーでリアルタイムの行を変更することはない。

### WebSocketとOBSへ送るメッセージ

```json
{"type": "SENT",
 "src_languages": {"1": {"language": "Japanese", "country": "Japan", "enable": true}},
 "dst_languages": {"1": {"language": "English", "country": "United States", "enable": true}, …},
 "message": "こんにちは", "translation": ["Hello"], "transliteration": […]}
```

`src_languages`と`dst_languages`は受付時に固定したタブの言語の組、`translation`は訳の配列である。`type`は`SENT`（マイク）、`RECEIVED`（スピーカーとOCR）、`CHAT`（入力欄）、`REALTIME_MIC`、`REALTIME_SPEAKER`のどれか。表示設定が変わったときは`{"type": "SETTINGS_UPDATED", "settings": {…}}`を送る（[外部インターフェース](external-interfaces.md#websocketサーバー)）。

### 内蔵モデルの取得への同意

`config.json`の`LEGACY_MODEL_DOWNLOAD_CONSENTS`は、モデルIDから確認済みの一覧を表すSHA-256文字列への辞書で、既定は`{}`。IDは`whisper:base`、`ctranslate2:m2m100_418M-ct2-int8`などである。値は`models/legacy_model_consent.py`がモデル名・提供元・ライセンス・重みのリポジトリと固定版・全ファイルの容量とSHA-256・同じ一式に含まれるtokenizerのリポジトリ・固定版・ファイル一覧をJSONにして計算する。ファイルのハッシュそのものではなく、確認した内容を識別する値である。

`/get/data/model_download_catalog`の`legacy_models`に、確認画面用の名前、提供元、ライセンス、非商用の制限、正確な`total_bytes`、`tokenizer_size_unknown`、`manifest_version`を返す。CTranslate2のtokenizerには同じ取得元と固定版、ファイルの容量・SHA-256、bundled: trueが入る。tokenizer_size_unknownはfalse、容量は重複して足さない。`/run/download_whisper_weight`と`/run/download_ctranslate2_weight`には`{weight_type, consent: true, manifest_version}`を送る。現在の一覧と一致する明示的な同意を受け取ったときだけ記録し、取得前に即時保存を試みる。保存失敗は通常の設定保存と同じ通知・再試行で扱う。

起動時の取得では、保存された値と現在のモデル一覧の値が一致するか確認する。版、ファイルの容量・SHA-256、ライセンス、tokenizerの版が変わると再確認が必要になる。古い値はファイルを削除する根拠にはしない。旧版からの移行時は記録なしとして扱い、`AUTO_DOWNLOAD_MODELS=True`や既存のNLLB選択から同意を推測しない。既に取得したファイルとモデルの選択は保持する。

### チャット読み取りの範囲

`OCR_CAPTURE_REGION`はデスクトップのウィンドウ用、`OCR_VR_CAPTURE_REGION`はWindowsのSteamVRヘッドセット映像の左目側用で、どちらも`config.json`に保存する。画面ごとに幅と高さに対する割合で指定する。

```json
{
  "OCR_CAPTURE_REGION": {"x": 0.6, "y": 0.1, "width": 0.2, "height": 0.2},
  "OCR_VR_CAPTURE_REGION": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
}
```

`x`と`y`は左上、`width`と`height`は幅と高さ。有限の数値で画面内に収まり、幅と高さはそれぞれ0.02以上を必要とする。既定値は両方とも全体。IPCのsetterは小数点以下4桁に丸めて同じ検証を行い、不正な範囲を保存・予約せず400を返す。

旧版の単一の範囲は、キー名を変えず`OCR_CAPTURE_REGION`でウィンドウ用として引き継ぐ。`OCR_VR_CAPTURE_REGION`がない保存ファイルには全体の範囲を補い、読み込み後の保存で書き込む。既存のVR用の値は保持する。不正な値はそのキーの既定値へ戻し、片方の範囲をもう片方へコピーしない。Linuxでも両方を保存するが、VR用の範囲は適用せず、設定ページにも編集欄を出さない。

`/get/data/ocr_capture_region`と`/set/data/ocr_capture_region`は引き続きウィンドウ用の矩形を扱う。VR用は`/get/data/ocr_vr_capture_region`と`/set/data/ocr_vr_capture_region`で同じ形を扱う。

`/get/data/ocr_capture_status`は次の状態を200の応答にまとめて返す。`active`は有効化済みで停止していないワーカーがあるかを示す。`source`は直近の取り込み結果の元で、画像がないときや停止中は`null`。Linuxでは`available_sources`は`["window"]`となる。`shared_window`はLinuxで利用者が共有したウィンドウの扱いを示す。共有されたウィンドウを読んでいる間は`"active"`、読んでいた共有が終わり、名前で探せるウィンドウもない間は`"ended"`、それ以外と停止中は`null`。共有されたウィンドウを読んでいる間も`source`は`"window"`のままとする。

```json
{
  "active": true,
  "source": "window",
  "shared_window": null,
  "available_sources": ["window", "vr"],
  "state": "reading",
  "stage": null,
  "error_code": null,
  "detector": "region"
}
```

`state`は`stopped`、`waiting`、`reading`、`retrying`のいずれか。`stage`は`activation`、`capture`、`detector`、`recognition`、`tick`、`null`で、待機中や失敗した段階を表す。`error_code`は失敗時の既存の`OCR_DISABLED_*`コード、それ以外は`null`。`detector`はワーカーが実際に採用した検出器で、範囲読みでは`region`、独自検出器では`vrct-vox-chatbox`。取得済みかどうかや使用設定とは別に扱う。停止中は`active: false`となり、`source`、`stage`、`error_code`、`detector`はすべて`null`にする。

設定ページを開いている間だけ、このエンドポイントを1秒ごとに1回問い合わせ、取り込み元と実行状態を同じ欄に表示する。この取得はワーカーの状態を見るだけで、デバイスの検査、画像の取り込み、モデルの読み込みは行わない。正常な応答は診断ログへ書かず、状態自体も保存しない。

### その他

| データ | 形 |
|---|---|
| ワードフィルター | 文字列の配列。重複は順を保って除く。一致すると`/run/word_filter`に`{"message": "Detected by word filter: …"}` |
| ホットキー | `{open_quick_chat, toggle_vrct_visibility, toggle_translation, toggle_transcription_send, toggle_transcription_receive, stop_voice, toggle_voice_mute, toggle_tts, toggle_rvc}`の各値が`["Ctrl","Shift","Q"]`のようなキーの配列か`null`。知らないキーを含むと全体を拒否する |
| 重みの取得状態 | 一覧は {種類: 取得済みか}。受付は {weight_type, job_id}。進捗は {weight_type, job_id, progress}、成功通知は {weight_type, job_id, downloaded: true}。失敗通知はエラー本体のdataに {weight_type, job_id, downloaded: false, reason} を入れる。進行中の同じ重みへの重複要求を拒否する場合はactive_job_idも付ける |
| エンジンの状態 | `{エンジン名: 使えるか}`。使えるエンジンの一覧は`selectable_*_engines`で配列として返す |
| エラー | [IPCプロトコル](ipc-protocol.md#エラーの本体) |

## config.json

- 置き場所は`$VRCT_CONFIG_DIR`、なければ実行ファイルのあるフォルダ（開発中は`src-python/`）。Linuxの配布版では`$XDG_CONFIG_HOME/vrct-vox`（なければ`~/.config/vrct-vox`）である。フォルダ名は保存先の識別子なので、変えるには移行の処理がいる（`docs/voice-stack/project-rename.md`）。
- 設定は`Config`クラスの`ManagedProperty`と`ValidatedProperty`で宣言し、既定値は`init_config()`にある。`serialize=True`のものだけを保存する。オンオフの状態（`ENABLE_*`）や選択肢の一覧は保存しない。
- 単純な設定プロパティは、未選択を表すモデル名と音声認識エンジンを除き`null`を受け付けない。APIキーやホットキーの辞書内にある未設定の`null`は維持する。数値のプロパティとオーバーレイの数値設定は`NaN`・無限大（`1e999`などの桁あふれも含む）を保存前に拒否する。不正な保存値は既定値へ戻す。メッセージ欄の比率と大小字幕の設定変更では400の`VALIDATION_CONFIG_VALUE_INVALID`を返し、`data`には保持した設定値を入れる。
- 読み込みでは、各キーを検証してから設定する。知らないキーは捨て、次に保存するとファイルからも消える。検証に通らないキーは既定値のままにしてerror.logに残す。ただしマイクとスピーカーの選択（`SELECTED_MIC_HOST`、`SELECTED_MIC_DEVICE`、`SELECTED_SPEAKER_DEVICE`）は、読み込む時点でデバイスの一覧がまだ取れていないため、保存値をそのまま受け取る。一覧が取れたあと、サイドカーがデバイスの有無を確かめ、無ければ既定のデバイスに戻す。JSONとして読めない、またはオブジェクトでないときは、そのファイルを名前の重複しない`config.json.unreadable-<日時>-<乱数>`に移して残し、既定値で起動する。UIは`/run/config_file_unreadable`を受けて、既定値で起動したことと残したファイルの場所を知らせる。
- メモリー上の初期値をすべて用意してからログ用ディレクトリを作る。ログ用ディレクトリを作れなくても、設定の初期化は完了させる。それ以外の初期化が途中で失敗したときは、不完全なインスタンスを公開せず、設定の読み込みも保存も行わない。読み込み中は保存せず、全項目の適用と移行が終わってから1回だけ保存する。読み取り権限の不足や退避の失敗では元のファイルを残し、[保存の失敗通知](cross-cutting.md#サイドカーでの保存)を出して以後の保存を止める。
- 版番号はない。入れ子の設定のうち`SPEECH_SERVER_SETTINGS`と`REALTIME_ASR_SETTINGS`は`"version": 1`を持つ。
- `OVERLAY_VR_LAUNCHER_SETTINGS`の`ui_scaling`は、ランチャーの帯が952px幅だとしたときの横幅（m）である。帯が880px幅になっても意味を変えない。版番号がなく移行済みかどうかを区別できないので保存値は書き換えず、実際の横幅を880/952倍して求める。保存値のまま、ボタンの大きさが変わらない。
- 保存済みの言語・翻訳エンジンの辞書が壊れているときは、不足・不正なタブや枠を既定値で補い、正常な部分は読み込む。余分なキーは捨てる。実行中の更新に対する構造の検証とは区別し、壊れた辞書で起動を妨げない。
- 書き込みは[横断的な振る舞い](cross-cutting.md#サイドカーでの保存)のとおり、2秒の遅延、0600の一時ファイル、`fsync`、置き換えの順に行う。
- 起動のたびに直す値がある: `SELECTED_RELEASE_CHANNEL`は版から決め直す。インストーラーが置いた`installer_language.txt`があればUIの言語にして消す。WebSocketのトークンは初回と不正な保存値の修復時に作って保存する（[ネットワーク設定](#ネットワーク設定)）。

## そのほかのファイル

| ファイル | 置き場所 | 内容 |
|---|---|---|
| `process.log`、`error.log`、`freeze_trace.log`、`crash_trace.log` | `$VRCT_CONFIG_DIR/logs/`（なければ作業フォルダ） | 診断ログ。`process.log`と`error.log`は10MBで切り詰め、`process.log`は起動のたびに空にする。`crash_trace.log`と`freeze_trace.log`（faulthandlerのスタックダンプ）は、起動のときに10MBを超えていたら新しい1MBだけを残す。`freeze_trace.log`には、フロントエンドからのfeedが`WATCHDOG_INTERVAL`＋15秒のあいだ来なかったときに、全スレッドのスタックを1回書く（プロセスは終了しない）。書くのはGILを持ったPythonのスレッドである。GILが返らない固まり方のときだけ、さらに30秒後にfaulthandlerのCのスレッドが書く（`src-python/freeze_dump.py`） |
| `startup_timing.log` | 同上 | 起動1回につき1行のJSON。段階ごとの実時間とCPU時間、遅かった`/get/data/…`、起動中のPC全体のCPU使用率を残す。`process.log`と違って次の起動でも消えない。段階名、エンドポイント名、数値だけで、パスやデバイス名は書かない。256KBを超えたら起動のときに新しい64KBだけを残す |
| `startup.log` | 同上（Tauri側） | ウィンドウの起動記録 |
| 会話ログ `YYYY-MM-DD_HH-MM-SS.log` | `PATH_LOGS` | 「会話ログを自動的に保存する」がオンのときだけ。行頭は`[SENT]`、`[RECEIVED]`、`[OCR]`、`[CHAT]`。画面は新しい1,000件しか残さないが、ファイルには古いものも残る |
| `downloaded_models/<id>/<版>/`と`receipt.json` | `config.json`と同じフォルダ | 取得したモデル。取得中は`.partial-<16進>/` |
| `vc_runtimes/<エンジン>/`と`receipt.json` | `config.json`と同じフォルダ | アプリが準備したRVCとSeed-VCの実行環境（WindowsとLinux）。`.steps.json`に終わった手順、`setup.log`に`uv`の出力を残す。`.uv-<版>/`に取得用の`uv`を置く |
| weights/whisper/…、weights/ctranslate2/… | PATH_DATA | 内蔵モデルと検証記録。取得も既存ファイルの利用もbuiltin_model_pins.pyの全容量・SHA-256を照合する。tokenizerも同じ一式に含む。検証記録はschema=2、repo・revision・全ファイルpinのSHA-256識別値、各ファイルのsize・mtime_ns・ctime_ns・device・inode。古い記録は無効。不一致の既存ファイルは残し、同意済みの再取得に成功した場合だけ既存一式を`.preserved-<weight>-<uuid>`へ移してから新しい一式を公開する |
| `voice_mute_state.json` | `config.json`と同じフォルダ | `{"version": 1, "muted": 真偽}`。すぐに書き、原子的に置き換える |
| `telemetry_state.json` | `PATH_DATA` | 送信しないテレメトリーの状態 |
| `io.github.kein5.vrct-vox.desktop` | `$XDG_DATA_HOME/applications/` | Waylandでショートカットを登録するためのデスクトップファイル |

UIは独自の状態を持たない（`localStorage`も使わない）。画面の状態はすべてサイドカーから受け取る。

### 文字起こしの診断ログ

通常の発話診断は、mic/speaker別の`[utterance-summary]`として`process.log`に残す。
最初の観測から60秒以上経った後、次の観測が来た時点で前の区間を出力する。
活動がなければ出力せず、タイマーや専用スレッドも使わない。停止・終了時には残りを出力する。
停止の待機上限を超えていたワーカーが後から完了した場合も、その残りを出力する。

件数と最大値は区間内の全観測、p50/p95は各段階の直近256件からnearest-rank方式で求める。
`n`は全観測数、`samples`は分位点に使った件数。時間の単位はms。
VADの無音待ち（`vad_wait_ms`）、蓄積音声長（`vad_buffer_ms`）、完成済み音声のキュー待ち、
ASR、翻訳、その他の出力処理を分ける。従来の`total_ms`はASR開始から出力完了までの処理時間の和で、
録音・VAD・キュー待ちは含まない。リアルタイム経路では、サーバーの発話開始/commitからfinal受信までを
`realtime_pending_ms`、final受信から処理完了までを`realtime_total_ms`とする。
サーバー内部のVAD待ちと推論時間は提供されないので、個別の計測値として扱わない。

失敗・例外は従来どおり即時に記録する。遅い処理も従来の詳細を残す。
診断用の基準は、VAD無音待ち1,536ms、蓄積音声15,000ms、キュー待ち/出力1,000ms、
ASR/翻訳5,000ms、従来のtotal 10,000ms。
リアルタイム経路ではpending 7,500ms、finalキュー待ち/翻訳1,000ms、final処理全体2,000ms。
これらは処理を打ち切る制限ではない。キュー落ちは最初の1件を即時記録し、連続した回数は集約し、
次の正常投入で復旧を記録する。停止まで正常投入がなければ`recovery=unconfirmed`とする。
音声や認識文は診断に含めず、文字起こしのIPC応答の既存の伏字処理も維持する。
新しい設定や環境変数はない。実装は`models/transcription/utterance_diagnostics.py`。

## 環境変数

| 変数 | 働き |
|---|---|
| `VRCT_CONFIG_DIR` | `config.json`、ログ、取得したモデル、ミュート状態の置き場所 |
| `VRCT_DATA_DIR`、`VRCT_CACHE_DIR` | Linux配布版のデータとキャッシュの置き場所 |
| `XDG_CONFIG_HOME`、`XDG_DATA_HOME`、`XDG_CACHE_HOME` | Linux配布版の既定の置き場所の元 |
| `HF_HOME` | 未設定なら`<キャッシュ>/huggingface`（Linux配布版） |
| `VRCT_VOICE_TRACE`、`VRCT_VOICE_GC_DIAGNOSTICS` | 読み上げの時間計測とGCの記録（診断用） |
| `WAYLAND_DISPLAY`、`XDG_SESSION_TYPE`、`GDK_BACKEND` | Quick Chatとホットキーの登録方法の判定 |
| `DISPLAY` | X11でのOCRのキャプチャ |
| `VRCT_VR_PANEL_DIR` | Tauriが起動時に決める、このプロセス専用の場所（`$XDG_RUNTIME_DIR/vrct-vox/vr-panel-<pid>`、Linux）。バックエンドはここでVR画面の画素（`frame`）と、共有されたウィンドウの画素（`screen-frame`）を読む。利用者が設定するものではない |
| `APPIMAGE`と`WEBKIT_DISABLE_DMABUF_RENDERER=1` | NVIDIA環境のAppImageでメインウィンドウを不透明にする |

`HF_HUB_OFFLINE`などのオフライン用の変数は、アプリは読まない。`tools/dev.py`が開発用の子プロセスに設定する。

## 音声デバイスの選択と識別

従来の文字起こしと音量メーターは、入力元ごとに1つの録音セッションを共有する。名前は表示用のラベルとし、選択にはIDを使う。

- 保存する`SELECTED_MIC_DEVICE_ID`と`SELECTED_SPEAKER_DEVICE_ID`を追加した。既存の`SELECTED_MIC_HOST`、`SELECTED_MIC_DEVICE`、`SELECTED_SPEAKER_DEVICE`は残す。名前だけの旧設定は、対象ホストの候補が1台に絞れるときだけIDへ移行する。同名の候補が複数あるときは手動で選び直す。保存したIDが見つからなくても、同名という理由で別の機器と同一視しない。
- PortAudioが返すエンドポイントID・UID、対応を一意に確認できるWindowsのIMMDevice ID、PipeWireのノード名を識別に使う。IDを取得できないPortAudioの機器には、プロセス内の一覧に限って有効なIDを付ける。このIDは再起動や接続状態の変更を越えて同じ機器を保証しない。名前の重複からWindowsのIDとの対応を推測しない。
- 録音開始時のPortAudio情報に、選択時に確認したネイティブIDが含まれない場合は、そのopenで使うPortAudioの一覧と新しいIMMDeviceの一覧から対応を確認する。別のIDならそのストリームを閉じて代替機器を探す。対応を確定できない場合は録音を続け、選択時のネイティブIDを引き継がず、実際に開いたスロットのIDと名前を通知する。
- 選択IDとは別に、接続状態の世代、PortAudioのインデックス、サンプルレート、入力チャンネル数を比較する。名前とIDが同じでも、これらが変われば録音を再設定する。
- 旧IPCの名前の文字列と名前一覧は維持する。新しい`/get/data/selectable_mic_device_options`とスピーカー側の同名形式は`[{id, label}]`を返す。`/get/data/selected_mic_device_id`、`/set/data/selected_mic_device_id`とスピーカー側の同名形式はID文字列を扱う。各値の変更は`/run/…`でも通知する。デスクトップとVRの選択欄は新しいIPCを使う。同名の項目にはIDも添える。旧名による変更要求は、候補が1台のときだけ受け付ける。
- 一覧の更新やAuto選択だけでは録音を始めない。Autoをオンにすると、選択値と収録中のデバイスを1回の処理で合わせる。更新中にAutoをオフにしても、利用者が始めた録音を継続する。OFF操作が終わった後に、古い再開要求で録音を再開しない。
- 利用者が始めた録音では、選択した機器が消えた場合や開けない場合、Autoがオフでも利用可能な別の機器へ切り替えて継続する（2026-11-04の保守方針）。ライブラリの既定値を識別しないまま開くことはしない。開けた機器のIDと名前を選択値として通知し、`/run/audio_device_switched`の200通知に`{source, old_device: {id, name}, new_device: {id, name}}`を入れる。UIは変更前後の名前を、操作を妨げない通知で知らせる。
- 代替機器でも開始できない場合、止まった文字起こしとメーターをオフにし、メーターをゼロへ戻す。開く処理がタイムアウトした場合も、その処理の所有権を保持する。処理が終わるまで同じ入力元の新しいopenを拒否し、遅れて開いた資源を閉じる。既に実行中のネイティブ呼び出しを強制的に中断できる保証はない。
- 録音のエラーと復旧処理は開始ごとの世代で照合する。古い録音のエラーで、切り替え後の録音を止めたり、新しいエラー通知を抑止したりしない。この世代は利用者のオン・オフ操作やメッセージ配送の世代と分け、内部のデバイス切り替えだけでは受け付け済みのテキストを破棄しない。検証のために開いたストリームは、リスナーが開始する前に停止された場合も一度だけ閉じる。

リアルタイムASRは別のキャプチャ経路であり、ここで述べた従来の録音の自動継続は適用しない。
