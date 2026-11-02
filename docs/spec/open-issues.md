# 未決事項

仕様書を作るために実装を調べて見つかった、食い違いや決まっていないこと。2026-11-02時点の記録で、直したら行を消す。直さないと決めたものは、理由を書いて残す。

| ID | 内容 | 根拠 | 状態 |
|---|---|---|---|
| OI-01 | VRパネルのウィンドウ名が一致しない可能性がある。Rustは`VRCT-VOX VR Panel`という名前でウィンドウを作るが、Windowsのオーバーレイは`FindWindowW`で`VRCT VR Panel`（`vr.html`の`<title>`）を探す。WebView2が文書の題名をウィンドウ名に写さなければ、Windowsでは取り込めない | `src-tauri/src/lib.rs`（ウィンドウ作成）、`src-python/models/overlay/window_capture.py` | Windowsの実機で未確認 |
| OI-03 | VRChatへ送る文に長さの上限や分割の処理がない。VRChat側の上限を超えたときの扱いが決まっていない | `src-python/models/osc/osc.py` | VRChat側の仕様が未確認 |
| OI-04 | `run_mapping`の`send_text_overlay`と`vr_launcher_reset`は定義だけで、送っている箇所がない | [IPCエンドポイント一覧](reference/ipc-endpoints.md)の「UIに受信先がないエンドポイント」 | 未着手 |
| OI-05 | 「最前面固定」はUIがウィンドウに直接設定し、サイドカーの`/set/enable/foreground`は使われていない。値は保存されず、再起動すると戻る | `src-ui/logics/main/useMainFunction.js` | 保存するかどうか未決 |
| OI-06 | `/run/enable_ai_models`を受けて更新する`IsVrctAvailable`を読む画面がない。いまはお知らせを出すだけである | `src-ui/logics/common/useIsVrctAvailable.jsx` | 未決 |
| OI-07 | UIだけにあるルートが57件ある。多くは`ui_config_setter.js`の定義が機械的に作るもので、使われない | [IPCエンドポイント一覧](reference/ipc-endpoints.md)の「UIだけにあるルート」 | 整理するか未決 |
| OI-08 | 要求に通し番号がなく、応答はエンドポイント名で対応づける。同じエンドポイントへの要求が重なると、どの応答がどの要求のものか分からない。言語の変更だけはUIが対応づけを補っている | [IPCプロトコル](ipc-protocol.md#言語の変更の対応づけ) | 設計上の制約。変えるならプロトコルの版を上げる |
| OI-09 | `config.json`に版番号がない。キーの意味を変えるときに移行の手がかりがない | [データ形式と保存](data-and-persistence.md#configjson) | 未決 |
| OI-10 | エラーコード96件のうち10件は、UIに個別の処理がない。いずれも音声認識の失敗（`AUDIO_*`、`ASR_ERROR`、`TRANSCRIPTION_API_*`など）で、`/run/transcription_recognition_error`として会話ログに出るため汎用の通知にはならない。`AUDIO_TRACKER_STOP_TIMEOUT`はテレメトリー用で画面には届かない | [エラーコード一覧](reference/error-codes.md) | 確認済み。新しいコードを足すときは同じ確認をする |
| OI-11 | VR UIの設定ウィンドウは、デスクトップの設定画面と違い「チャット読み取り」と「その他」のタブのまま。デスクトップでは2026-11-02にVRChatページへまとめた | `src-ui/views/vr/VrSettingsWindow.jsx` | VR側もそろえるか未決 |
| OI-13 | 内蔵の翻訳（CTranslate2とトークナイザー）とWhisperの重みは、Hugging Faceの既定の版を取得し、版、サイズ、SHA-256を確かめない。モデル取得の画面（`models/model_downloads/`）のような固定がない | `src-python/models/translation/translation_utils.py`、`src-python/models/transcription/transcription_whisper.py` | 移す作業が未着手 |
| OI-15 | Linuxのビルドは`uv export --no-hashes`で依存を書き出すため、`uv.lock`にあるパッケージのハッシュを確かめない。commitで固定したVCSの依存と両立させる必要がある | `tools/build_linux.py` | 未着手 |
| OI-17 | 会話ログはUIのメモリーと画面に際限なく残り、VR UIがオンなら変わるたびに全件をVRパネルへ送る。長時間使うと遅くなる | `src-ui/logics/common/useMessage.js`、`VrPanelSyncController.jsx` | 上限を設けるか未決 |
| OI-19 | LLMの訳が長さの上限で切れても（`finish_reason`が`length`）、成功として扱う。空の訳だけは失敗にした | `src-python/models/translation/translation_openai.py`、`translation_lmstudio.py` | 未着手 |
| OI-20 | WebSocketサーバーの起動が6秒を超えると失敗として返すが、その起動の試みは止めない。遅れて起動したり、次の起動の後片付けと重なったりするおそれがある（実際には確かめていない） | `src-python/model.py`（`startWebSocketServer`） | 未確認 |

## 調べて直したもの

仕様書を作る途中で見つけ、同じ時期に直したもの。

- OBSブラウザソースが認証なしでWebSocketのトークンを返していた（OI-12、SEC-01）。ページのURLにも同じトークンを必須にし、設定画面にURLのコピーし直しを案内した。
- 翻訳をオンにしたときのVRAM不足の通知が、存在しない`run_mapping`の名前を使って例外になっていた。
- 文字起こし中に入力デバイスがないときの通知にエラーコードがなく、汎用の通知になっていた。
- Deepgramのキーの確認が、認証なしでも成功する`/v1/models`で行われていた。
- OpenAIの`gpt-4o-transcribe`系に、対応していない`verbose_json`を要求していた。
- 設定値が拒否されたとき（`VALIDATION_CONFIG_VALUE_INVALID`）、UIに分岐がなく「開発者に連絡」の通知になっていた。
- 使われていないTauriのコマンド`download_zip_asset`が任意のURLを取得できた（OI-02）。コマンドと、そのためだけの依存（reqwest、base64）を外した。
- VRCマイクミュート同期がOSCの`false`だけで文字起こしを再開していた（OI-14、SEC-05）。VRChatのOSCQueryで解除を確認し、確認できない間はミュートを保つようにした。
- 起動時のAPIキーの確認に失敗すると、キーを消していた。オフラインで起動するだけで保存したキーがすべて消えた。キーを入れ直して確認に失敗したときも、保存してあったキーを消していた。
- 起動時のOllamaのモデル一覧の取得に時間の上限がなく、応答が止まると起動が終わらなかった。
- LLMが空の訳を返すと成功として扱い、訳だけを送る設定では何も送らなかった。
- WebSocketサーバーの実際のbindが失敗しても、有効にしたと返していた。
- VRパネルへ写す状態に認証キーとトークンが入っていた。VRパネルから接続先のURLを変えられ、保存したキーをその接続先へ送らせられた。
- 読めない`config.json`を既定値で上書きしていた。サイドカーが落ちても知らせなかった。サイドカーのエラーを英語のまま出していた。
- 起動時のエンジンの確認に全体の時間の上限がなく、応答を少しずつ返し続けるサーバーがあると起動が終わらなかった（OI-18）。段階ごとに30秒で打ち切り、間に合わなかったエンジンは使えない状態で起動する。
- `config.json`の書き込みに失敗しても、例外を捨てて成功を返していた（OI-16）。UIに理由を知らせ、30秒ごとに書き直す。
