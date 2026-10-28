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
