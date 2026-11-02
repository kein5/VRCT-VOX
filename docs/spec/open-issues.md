# 未決事項

仕様書を作るために実装を調べて見つかった、食い違いや決まっていないこと。2026-11-02時点の記録で、直したら行を消す。直さないと決めたものは、理由を書いて残す。

| ID | 内容 | 根拠 | 状態 |
|---|---|---|---|
| OI-01 | VRパネルのウィンドウ名が一致しない可能性がある。Rustは`VRCT-VOX VR Panel`という名前でウィンドウを作るが、Windowsのオーバーレイは`FindWindowW`で`VRCT VR Panel`（`vr.html`の`<title>`）を探す。WebView2が文書の題名をウィンドウ名に写さなければ、Windowsでは取り込めない | `src-tauri/src/lib.rs`（ウィンドウ作成）、`src-python/models/overlay/window_capture.py` | Windowsの実機で未確認 |
| OI-02 | Tauriのコマンド`download_zip_asset`が登録されているが、UIから呼ばれていない。任意のURLを取得できるため、使わないなら外す | `src-tauri/src/lib.rs` | 未着手 |
| OI-03 | VRChatへ送る文に長さの上限や分割の処理がない。VRChat側の上限を超えたときの扱いが決まっていない | `src-python/models/osc/osc.py` | VRChat側の仕様が未確認 |
| OI-04 | `run_mapping`の`send_text_overlay`と`vr_launcher_reset`は定義だけで、送っている箇所がない | [IPCエンドポイント一覧](reference/ipc-endpoints.md)の「UIに受信先がないエンドポイント」 | 未着手 |
| OI-05 | 「最前面固定」はUIがウィンドウに直接設定し、サイドカーの`/set/enable/foreground`は使われていない。値は保存されず、再起動すると戻る | `src-ui/logics/main/useMainFunction.js` | 保存するかどうか未決 |
| OI-06 | `/run/enable_ai_models`を受けて更新する`IsVrctAvailable`を読む画面がない。いまはお知らせを出すだけである | `src-ui/logics/common/useIsVrctAvailable.jsx` | 未決 |
| OI-07 | UIだけにあるルートが57件ある。多くは`ui_config_setter.js`の定義が機械的に作るもので、使われない | [IPCエンドポイント一覧](reference/ipc-endpoints.md)の「UIだけにあるルート」 | 整理するか未決 |
| OI-08 | 要求に通し番号がなく、応答はエンドポイント名で対応づける。同じエンドポイントへの要求が重なると、どの応答がどの要求のものか分からない。言語の変更だけはUIが対応づけを補っている | [IPCプロトコル](ipc-protocol.md#言語の変更の対応づけ) | 設計上の制約。変えるならプロトコルの版を上げる |
| OI-09 | `config.json`に版番号がない。キーの意味を変えるときに移行の手がかりがない | [データ形式と保存](data-and-persistence.md#configjson) | 未決 |
| OI-10 | エラーコード96件のうち10件は、UIに個別の処理がない。いずれも音声認識の失敗（`AUDIO_*`、`ASR_ERROR`、`TRANSCRIPTION_API_*`など）で、`/run/transcription_recognition_error`として会話ログに出るため汎用の通知にはならない。`AUDIO_TRACKER_STOP_TIMEOUT`はテレメトリー用で画面には届かない | [エラーコード一覧](reference/error-codes.md) | 確認済み。新しいコードを足すときは同じ確認をする |

## 調べて直したもの

仕様書を作る途中で見つけ、同じ時期に直したもの。

- 翻訳をオンにしたときのVRAM不足の通知が、存在しない`run_mapping`の名前を使って例外になっていた。
- 文字起こし中に入力デバイスがないときの通知にエラーコードがなく、汎用の通知になっていた。
- Deepgramのキーの確認が、認証なしでも成功する`/v1/models`で行われていた。
- OpenAIの`gpt-4o-transcribe`系に、対応していない`verbose_json`を要求していた。
- 設定値が拒否されたとき（`VALIDATION_CONFIG_VALUE_INVALID`）、UIに分岐がなく「開発者に連絡」の通知になっていた。
