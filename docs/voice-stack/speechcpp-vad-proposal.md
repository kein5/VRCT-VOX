# speech.cpp Realtime用Silero VADの取得候補

状態: **取得同意待ち。重みは未取得**（2026-10-28）。

P3仕様の`server_vad`はspeech.cppサーバに検出モデルを必要とする。Seed-VCで同意済みのFSMN-VADとは別artifact。
導入済みspeech.cpp0.9.0の固定catalogと配布元モデルカードが、次の1ファイルのサイズ/SHA256で一致した。

| 項目 | 値 |
|---|---|
| Repository | `sakasegawa/silero-vad-GGUF` |
| Revision | `7fcb7aa2a70c312f8579fc987b3e1cdecf9321ca` |
| File | `silero-vad-309K-v6.2-F32.gguf` |
| Size | 1,238,624 bytes（約1.24MB） |
| SHA256 | `2fc312514e5fc4fa4ffd02b25c76a4853fa4130e8fb9777d01502183b01238cb` |
| License | MIT（モデルカードと付属LICENSE。最終配布時は通知を保持） |
| 保存予定 | `tmp/voice-resume/asr-poc/assets/`内。既存cache/製品配布物を変更しない |

同意後は固定URLのみから取得しhash照合、既存ReazonSpeechと同時に隔離サーバへロードする。
既存合成ファイルを24kHz mono PCMに明示変換し、speech_started/delta/completedを検証。
新しい声の録音、追加ASRモデル、TTS/VCモデルや参照音声の取得はこの候補に含めない。
モデルなしで進められるWSイベント順序/重複排除/期限の模擬試験は並行して行える。

根拠: [固定カード](https://huggingface.co/sakasegawa/silero-vad-GGUF/blob/7fcb7aa2a70c312f8579fc987b3e1cdecf9321ca/README.md)、
[固定LICENSE](https://huggingface.co/sakasegawa/silero-vad-GGUF/blob/7fcb7aa2a70c312f8579fc987b3e1cdecf9321ca/LICENSE)、
[公式v0.9.0 Realtime](https://github.com/nyosegawa/speech.cpp/blob/49f022a48bc1c7e797aa64dd08d2d9655baf299e/docs/server.md#realtime-transcription)。
仕様書§8の「モデル取得はユーザー同意のうえ」に従い、新規artifactへの同意が必要。
既存5モデルの承認をこの別モデルへ拡張して解釈しない。
