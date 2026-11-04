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

### 音声認識のしきい値

マイクとスピーカーの`avg_logprob`は−2以上0以下、`no_speech_prob`は0以上1以下の有限の数値を受け付ける。IPCでは数値に変換できる文字列も受け付ける。`NaN`・無限大、範囲外、真偽値などは変更や保存をせず400の`VALIDATION_CONFIG_VALUE_INVALID`で拒否し、`data`に元の値を返す。保存済みの不正な値は読み込み時に既定値へ戻す。

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

- 入力欄からは`/run/send_message_box`に`{"id", "message"}`を送り、応答で上の形を受け取る。UIは送る前に行を「送信中」として出し、200の応答で送信中を解除する。同じ行のIDと時刻を保ち、応答の`original`と`translations`に読みも含めて更新する。Quick Chatからの送信とVRパネルに映す行も同じ処理を使う。デスクトップでは待機中のアイコンが回転し、VRパネルでは動かない文言で示す。
- 通信失敗、400・404・423・500の応答、バックエンドの停止では、該当する送信中の行を`status: "failed"`にし、本文を残して「送信を確認できません」と表示する。自動では再送しない。エラー応答にIDがない場合は送信中の全行を対象にする。その後にID付きの200が届けば、その行の状態、読みを含む原文と訳を更新する。
- 各出力の失敗は、別の400通知`/run/message_output_error`でも知らせる。`result.data`は`{id, source, output, error_code}`で、`id`がない入力では`null`。`source`は`chat`・`mic`・`speaker`・`ocr`、`output`は`osc`・`overlay_small`・`overlay_large`・`clipboard`・`ui`・`websocket`・`logger`・`history`・`tts`のいずれか。本文や例外の詳細は入れない。UIへの通常通知の後に失敗する出力もあるため、全入力元の失敗通知をこの経路で扱う。送信行を失敗扱いにせず、出力先ごとに警告を表示する。
- マイクは`/run/transcription_send_mic_message`、スピーカーは`/run/transcription_receive_speaker_message`、OCRは`/run/transcription_ocr_message`で届く。

### リアルタイム字幕と配送結果

リアルタイム音声認識は200の`/run/realtime_caption`で通知する。行は`source`（`mic`・`speaker`）、`generation`、`namespace`、`item_id`の組で識別する。`revision`は同じ行の更新番号である。

`partial`は認識途中、`final`は認識の確定であり、どちらも配送完了ではない。`text`に認識文、`translations`に訳の配列を持つ。`translated`は原文の読みを含む`original`と`translations`を更新するが、配送の待機は解除しない。`discarded`は空の確定結果や、表示前に期限が切れた字幕を退役させる。

表示した空でない`final`には、次の結果通知を1回発行する。`revision`は`final`より2大きい。本文と訳はこの通知に含めず、同じ行に保持する。

```json
{"status": 200, "endpoint": "/run/realtime_caption", "result": {
  "source": "mic", "generation": 4, "namespace": "session", "item_id": "utterance",
  "revision": 3, "state": "outcome", "outcome": "not_delivered", "reason": "expired"
}}
```

| `outcome` | `reason` | 行の状態と意味 |
|---|---|---|
| `delivered` | `null` | `status: "ok"`。適用対象の出力処理を終えた。マイクは「送信」、スピーカーは「受信」。VRChatでの受信確認やTTSの再生完了は意味しない |
| `not_delivered` | `expired`・`revoked`・`superseded`・`filtered` | `status: "not_sent"`。2秒の期限切れ、配送世代やセッションの失効、新しい文を送信済みのためチャットボックスへの送信を省略、ワードフィルターによる省略。処理失敗とは区別する |
| `failed` | `processing_failed`・`queue_full` | `status: "failed"`。処理自体の例外・VRAM不足、または確定結果の待ち行列が満杯。本文を残す |

出力先だけの例外では`delivered`を維持し、既存の`MESSAGE_OUTPUT_FAILED`警告を使う。行に警告を重ねない。期限切れ・失効、またはチャットボックスの送信省略も起きた場合は、その`not_delivered`を表示する。既に終えた出力は取り消さず、自動で再送しない。

認識が確定した行は`status: "pending"`で始める。デスクトップのマイク行は「送信中…」と待機アイコン、スピーカー行は「処理中…」を使う。VRパネルは同じ行を映し、待機アイコンを動かさず文言で示す。処理失敗のマイク行は既存の「送信を確認できません」、スピーカー行は「処理に失敗しました」と表示する。送信を省略したマイク行は理由を添え、スピーカー行は「処理を中止しました」と表示する。

待ち行列で期限が切れた結果も、停止・ミュート・終了で処理へ進めなかった結果も、表示済みなら結果通知を出す。読取ワーカーが既存の待機周期で期限と配送世代を確認するため、翻訳の終了を待たずに行を確定できる。表示しなかった確定結果には出さない。停止後や新しいセッションの開始後でも、UIに残っている同じIDの確定行だけを更新する。未知・削除済み・認識途中の行には適用せず、一度確定した結果は後続の通知で変えない。

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

### その他

| データ | 形 |
|---|---|
| ワードフィルター | 文字列の配列。重複は順を保って除く。一致すると`/run/word_filter`に`{"message": "Detected by word filter: …"}` |
| ホットキー | `{open_quick_chat, toggle_vrct_visibility, toggle_translation, toggle_transcription_send, toggle_transcription_receive}`の各値が`["Ctrl","Shift","Q"]`のようなキーの配列か`null`。知らないキーを含むと全体を拒否する |
| 重みの取得状態 | 一覧は {種類: 取得済みか}。受付は {weight_type, job_id}。進捗は {weight_type, job_id, progress}、成功通知は {weight_type, job_id, downloaded: true}。失敗通知はエラー本体のdataに {weight_type, job_id, downloaded: false, reason} を入れる。進行中の同じ重みへの重複要求を拒否する場合はactive_job_idも付ける |
| エンジンの状態 | `{エンジン名: 使えるか}`。使えるエンジンの一覧は`selectable_*_engines`で配列として返す |
| エラー | [IPCプロトコル](ipc-protocol.md#エラーの本体) |

## config.json

- 置き場所は`$VRCT_CONFIG_DIR`、なければ実行ファイルのあるフォルダ（開発中は`src-python/`）。Linuxの配布版では`$XDG_CONFIG_HOME/vrct-vox`（なければ`~/.config/vrct-vox`）である。フォルダ名は保存先の識別子なので、変えるには移行の処理がいる（`docs/voice-stack/project-rename.md`）。
- 設定は`Config`クラスの`ManagedProperty`と`ValidatedProperty`で宣言し、既定値は`init_config()`にある。`serialize=True`のものだけを保存する。オンオフの状態（`ENABLE_*`）や選択肢の一覧は保存しない。
- 読み込みでは、各キーを検証してから設定する。知らないキーは捨て、次に保存するとファイルからも消える。検証に通らないキーは既定値のままにしてerror.logに残す。ただしマイクとスピーカーの選択（`SELECTED_MIC_HOST`、`SELECTED_MIC_DEVICE`、`SELECTED_SPEAKER_DEVICE`）は、読み込む時点でデバイスの一覧がまだ取れていないため、保存値をそのまま受け取る。一覧が取れたあと、サイドカーがデバイスの有無を確かめ、無ければ既定のデバイスに戻す。JSONとして読めない、またはオブジェクトでないときは、そのファイルを`config.json.unreadable-<日時>`に移して残し、既定値で起動する。UIは`/run/config_file_unreadable`を受けて、既定値で起動したことと残したファイルの場所を知らせる。
- 版番号はない。入れ子の設定のうち`SPEECH_SERVER_SETTINGS`と`REALTIME_ASR_SETTINGS`は`"version": 1`を持つ。
- 保存済みの言語・翻訳エンジンの辞書が壊れているときは、不足・不正なタブや枠を既定値で補い、正常な部分は読み込む。余分なキーは捨てる。実行中の更新に対する構造の検証とは区別し、壊れた辞書で起動を妨げない。
- 書き込みは[横断的な振る舞い](cross-cutting.md#サイドカーでの保存)のとおり、2秒の遅延、0600の一時ファイル、`fsync`、置き換えの順に行う。
- 起動のたびに直す値がある: `SELECTED_RELEASE_CHANNEL`は版から決め直す。インストーラーが置いた`installer_language.txt`があればUIの言語にして消す。WebSocketのトークンは初回に作って保存する。

## そのほかのファイル

| ファイル | 置き場所 | 内容 |
|---|---|---|
| `process.log`、`error.log`、`freeze_trace.log`、`crash_trace.log` | `$VRCT_CONFIG_DIR/logs/`（なければ作業フォルダ） | 診断ログ。`process.log`と`error.log`は10MBで切り詰め、`process.log`は起動のたびに空にする。`crash_trace.log`と`freeze_trace.log`（faulthandlerのスタックダンプ）は、起動のときに10MBを超えていたら新しい1MBだけを残す |
| `startup.log` | 同上（Tauri側） | ウィンドウの起動記録 |
| 会話ログ `YYYY-MM-DD_HH-MM-SS.log` | `PATH_LOGS` | 「会話ログを自動的に保存する」がオンのときだけ。行頭は`[SENT]`、`[RECEIVED]`、`[OCR]`、`[CHAT]`。画面は新しい1,000件しか残さないが、ファイルには古いものも残る |
| `downloaded_models/<id>/<版>/`と`receipt.json` | `config.json`と同じフォルダ | 取得したモデル。取得中は`.partial-<16進>/` |
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
| `APPIMAGE`と`WEBKIT_DISABLE_DMABUF_RENDERER=1` | NVIDIA環境のAppImageでメインウィンドウを不透明にする |

`HF_HUB_OFFLINE`などのオフライン用の変数は、アプリは読まない。`tools/dev.py`が開発用の子プロセスに設定する。
