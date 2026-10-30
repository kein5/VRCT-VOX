# speech.cpp専用REST ASR（2026-10-28）

ローカルspeech.cppへの専用REST adapterとファイル入力CLIを実装した。既存ASR provider/UIは変更しておらず、P3全体の完成ではない。

- `src-python/models/transcription/speechcpp_asr.py`: 認識モデル/task/言語を確認し、WAVと必要なmodel/language/response_format=jsonだけを送る。temperature、Whisper固有のconfidence仮定を使わない。
- 元PCMのrate/channelsをWAVへ保持。空/60秒超/24MiB超は送信しない。モデル未検出や非対応言語では音声POSTをしない。
- localhost HTTPのみ、proxy/redirectを使わない。応答最大1MiB、preflightから本文終端まで既定15秒。接続済みsocketをキャンセルで中断する。
- `X-Speech-Stop=complete`だけを結果として返す。model_limitは不完全として拒否。空の認識文字列は有効な空結果。検出言語・confidenceを捏造しない。
- CLIの報告にはhash/音声長/文字数/所要時間のみ保存し、書き起こし・原音path・音声を含めない。入力はユーザーが明示するローカルWAV。

## 検証

実装前27 FAIL→実装後27 PASS。ネットワーク隔離下の実speech.cpp0.9.0 / 既存ReazonSpeech Q8_0も含め28 PASS（1.28秒）。
4.88秒・48kHz monoの既存合成音声を認識した。CLIのpreflight込み所要時間48.39ms（1回）。
これは音声区間全体を用意してからのREST時間であり、発話終了検出/物理capture/字幕表示の遅延でも、p50/p95でもない。
誤モデル・誤言語の2ケースは音声を送らず終了し、サーバlogのPOSTは成功したadapter/CLIの2回だけ。
新規モデル取得・録音・ホスト音声設定変更なし。rawは`tmp/voice-resume/asr-adapter-live/`、probeは`tmp/voice-resume/asr-rest-probe/`。

音声+既存provider/transcriberは470 PASS / 9 opt-in SKIP / 7 warnings。
既定suite1173 PASS / 16既知FAIL / 6 SKIP / 46 warnings。失敗名集合は以前と同一で、[一覧](seed-vc-runtime-report.md#unchanged-default-suite-failures)を参照。

## 原典と残件

[固定v0.9.0公式REST仕様](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/docs/server.md#transcriptions)と実`/v1/models`を照合した。
新規依存なし。既存ReazonSpeechのmetadataはApache-2.0、元モデルrevision33693408be76b7cba9fd4a7546a0a8772430211b。
モデル同梱や新規配布はしていない。

Realtime WS、Silero VAD、mic/speaker capture、finalのdedup/翻訳/OSC/TTS連携、設定/UI、実機性能は次工程。
短いREST成功を長い発話や多言語の精度保証として扱わない。

## 独立レビューと修正

Critical0 / Important1 / Minor1。accept待ち行列が満杯だと接続中の取消しがtimeoutまで待つ問題を、実socketで再現して修正した。
nonblocking connectを20ms以下の指定間隔で待ち、取消し/共通期限を確認。writefds/exceptfdsの両方とSO_ERRORで完了を判定する。
指定20msはOSスケジューリング込みの硬い保証ではない。修正前1.54秒の再現失敗→修正後は500ms未満の上限テストを通過。
実サーバ含む29 PASS、関連471 PASS / 9 SKIP / 7 warnings。既定1173 PASS / 16既知FAIL / 6 SKIP、同一失敗名集合。

imozuruの2検索役で[Python socket](https://docs.python.org/3.11/library/socket.html#socket.socket.connect_ex)→
[CPython固定実装](https://github.com/python/cpython/blob/v3.11.10/Modules/socketmodule.c)、
[Linux connect](https://man7.org/linux/man-pages/man2/connect.2.html)、
[Winsock select](https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-select)を照合。
原典5本・検証済み7抜粋・5queryの結果25URL（2batch）を`tmp/voice-resume/research/asr-connect-cancel/`に保存。
Windows実機の検証は残る。

保留Minor: 深い入れ子JSONではASRErrorではなくRecursionErrorになり得る。本文漏洩・不完全結果の確定はないが、呼出側の例外処理に注意が必要。
判断: Realtime/UI/capture/下流確定処理は次工程（UI選択はまだ不可）、長文/多言語/競合/30分性能は未保証、
P2の41秒継続試験は元の限定条件だけを根拠とし、このASRレビューで再測定したとは扱わない。
