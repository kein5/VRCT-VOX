# P1トラブルシューティング

| 状態 | 確認すること |
|---|---|
| `http_404` / `http_503` | speech.cppでTTSモデルを読み込み済みか。別taskのサーバーではないか |
| `http_400` | 登録voice名・language。推測したモデル別オプションを追加しない |
| `expected_pcm` / `invalid_sample_rate` | `/v1/audio/speech`がaudio/pcmと正しいX-Sample-Rateを返すか |
| `transport_error` / `request_timeout` | localhostのポート・サーバー稼働・GPU負荷。途中からの自動再送はしない |
| `first_audio_timeout` | 応答ヘッダ＋最初のPCMが10秒内に届かなかった。モデルwarmup、文の長さ、GPU負荷を確認。接続/後続readは2秒、要求全体は30秒 |
| `language_or_text_unavailable` | 自分の言語、選択した翻訳先、有効な訳文、他言語サーバーの別ポート |
| `audio_devices_unavailable` | WindowsはPyAudioWPatch、Linuxはpw-dumpとユーザーのPipeWireセッション |
| `output_missing*` / `output_disconnected` | 一覧更新・明示再選択。既定デバイスへ自動切替しない |
| `output_stalled` / `output_drain_timeout` | PipeWireグラフのsink/source接続、VRChat入力選択 |
| 二重発声 | 外部の読み上げツール（上流作者のVRCT-TTSなど）をOFF。同じ文でも別IDの新規送信は別発声 |
| 待機中だが発声なし | キューoverflow/5秒超過は破棄。`/get/data/voice_status`のdroppedを確認 |
| VRChatメーターは動くがテストは無音 | マイクテストは短く録音して再生するため、入力が来ている間に`New Test`を開始。メニュー音、VRChat Master/マイク音量、OS出力のミュートも確認 |

TTSが無効/失敗しても既存の文字送信を維持する。受信/マイク/OCRをP1のTTSへは送らない。
内部イベントの重複除去は同じsource/event IDを120秒・最新512件まで記憶する。
翻訳中のstop/設定変更は世代番号で旧要求を無効化する。
ログ/状態は数値とエラーコードだけで、HTTP本文や音声を新たに保存しない。
設定UIの声名はserveの登録名を入力する方式。自動voice列挙やモデル取得はない。
