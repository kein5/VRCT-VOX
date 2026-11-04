<!-- 自動生成。手で編集しない。`python tools/spec_catalog.py --write`で更新する。 -->

# エラーコード一覧

`src-python/errors.py`の`ErrorCode`と`ERROR_METADATA`から生成した。応答の形とUIでの見せ方は[横断的な振る舞い](../cross-cutting.md#エラーの扱い)にある。

- 既定メッセージ: サイドカーが返す英語の`message`。UIは多くの場合`locales/`の文言に置き換えて表示する。
- UIの個別処理: `_useBackendErrorHandling.js`に専用の分岐（値の巻き戻しや翻訳した文言の表示）がある。空欄のコードは、音声やモデル取得など別の経路で処理されるか、汎用の通知になる。

## コード（104件）

| コード | 分類 | 既定メッセージ | 重大度 | 利用者の対処 | UIの個別処理 |
|---|---|---|---|---|---|
| `MESSAGE_OUTPUT_FAILED` | general | One message output failed; other outputs continued. Resending may duplicate delivery. | warning |  | あり |
| `DEVICE_NO_MIC` | device | No mic device detected | error | 要 | あり |
| `DEVICE_NO_SPEAKER` | device | No speaker device detected | error | 要 | あり |
| `AUDIO_OPEN_ERROR` | device | Audio device could not be opened | error | 要 |  |
| `AUDIO_READ_ERROR` | device | Audio capture failed | error | 要 |  |
| `VAD_INFERENCE_ERROR` | transcription | Voice activity detection failed | error | 要 |  |
| `TRANSCRIBER_INIT_ERROR` | transcription | Speech recognizer initialization failed | error | 要 |  |
| `ASR_ERROR` | transcription | Speech recognition failed | error | 要 |  |
| `CLEANUP_TIMEOUT` | transcription | Audio transcription cleanup timed out | error | 要 |  |
| `AUDIO_TRACKER_STOP_TIMEOUT` | device | Audio endpoint tracker cleanup timed out | warning |  |  |
| `TRANSLATION_ENGINE_LIMIT` | translation | Translation engine limit error | warning |  | あり |
| `TRANSLATION_VRAM_CHAT` | translation | VRAM out of memory during translation of chat | critical | 要 | あり |
| `TRANSLATION_VRAM_MIC` | translation | VRAM out of memory during translation of mic | critical | 要 | あり |
| `TRANSLATION_VRAM_SPEAKER` | translation | VRAM out of memory during translation of speaker | critical | 要 | あり |
| `TRANSLATION_VRAM_ENABLE` | translation | VRAM out of memory enabling translation | critical | 要 | あり |
| `TRANSLATION_DISABLED_VRAM` | translation | Translation disabled due to VRAM overflow | critical | 要 | あり |
| `TRANSLATION_MODEL_MISSING` | translation | The CTranslate2 model is not downloaded; translation was not enabled | error | 要 | あり |
| `TRANSLATION_MODEL_LOAD_FAILED` | translation | The CTranslate2 model could not be loaded; translation was not enabled | error | 要 | あり |
| `TRANSLATION_LANGUAGE_UNSUPPORTED` | translation | The selected translation model does not support a selected language; it was reset | warning |  | あり |
| `TRANSCRIPTION_VRAM_MIC` | transcription | VRAM out of memory during mic transcription | critical | 要 | あり |
| `TRANSCRIPTION_VRAM_SPEAKER` | transcription | VRAM out of memory during speaker transcription | critical | 要 | あり |
| `TRANSCRIPTION_SEND_DISABLED_VRAM` | transcription | Transcription send disabled due to VRAM overflow | critical | 要 | あり |
| `TRANSCRIPTION_RECEIVE_DISABLED_VRAM` | transcription | Transcription receive disabled due to VRAM overflow | critical | 要 | あり |
| `TRANSCRIPTION_SEND_NOT_READY` | transcription | Realtime microphone recognition is not ready | error | 要 | あり |
| `TRANSCRIPTION_RECEIVE_NOT_READY` | transcription | Realtime speaker recognition is not ready | error | 要 | あり |
| `TRANSCRIPTION_ENGINE_NOT_SELECTED` | transcription | Choose a speech recognition engine before enabling transcription. | warning | 要 | あり |
| `TRANSCRIPTION_MODEL_MISSING` | transcription | Whisper model files are missing or invalid. Review the model download before trying again. | error | 要 | あり |
| `TRANSCRIPTION_ENGINE_UNAVAILABLE` | transcription | The selected speech recognition engine could not start. Check its settings. | error | 要 | あり |
| `TRANSCRIPTION_API_AUTH_FAILED` | transcription | Transcription API rejected the configured API key | error | 要 | あり |
| `TRANSCRIPTION_API_RATE_LIMITED` | transcription | Transcription API rate limit exceeded | warning |  |  |
| `TRANSCRIPTION_API_TIMEOUT` | transcription | Transcription API request timed out | warning |  |  |
| `TRANSCRIPTION_API_SERVER_ERROR` | transcription | Transcription API returned a server error | warning |  |  |
| `WEIGHT_CTRANSLATE2_DOWNLOAD` | weight | CTranslate2 weight download error | error | 要 | あり |
| `WEIGHT_WHISPER_DOWNLOAD` | weight | Whisper weight download error | error | 要 | あり |
| `WEIGHT_DOWNLOAD_CONSENT_REQUIRED` | weight | Review the model license and size in Settings and consent to this exact model manifest before downloading | warning | 要 | あり |
| `WEIGHT_CTRANSLATE2_LICENSE_CONSENT_REQUIRED` | weight | This translation model has a non-commercial license (CC-BY-NC-4.0) and must be confirmed explicitly | warning | 要 | あり |
| `WEIGHT_CTRANSLATE2_NON_COMMERCIAL_NOTICE` | weight | The selected translation model has a non-commercial license (CC-BY-NC-4.0) | warning |  | あり |
| `UPDATE_SOFTWARE_DOWNLOAD` | general | Software update download error | error | 要 | あり |
| `UPDATE_SOFTWARE_VERIFY` | general | Software update verification error | error | 要 | あり |
| `VALIDATION_MIC_THRESHOLD` | validation | Mic energy threshold value is out of range | warning | 要 | あり |
| `VALIDATION_SPEAKER_THRESHOLD` | validation | Speaker energy threshold value is out of range | warning | 要 | あり |
| `VALIDATION_MIC_RECORD_TIMEOUT` | validation | Mic record timeout value is out of range | warning | 要 | あり |
| `VALIDATION_MIC_PHRASE_TIMEOUT` | validation | Mic phrase timeout value is out of range | warning | 要 | あり |
| `VALIDATION_MIC_MAX_PHRASES` | validation | Mic max phrases value is out of range | warning | 要 | あり |
| `VALIDATION_SPEAKER_RECORD_TIMEOUT` | validation | Speaker record timeout value is out of range | warning | 要 | あり |
| `VALIDATION_SPEAKER_PHRASE_TIMEOUT` | validation | Speaker phrase timeout value is out of range | warning | 要 | あり |
| `VALIDATION_SPEAKER_MAX_PHRASES` | validation | Speaker max phrases value is out of range | warning | 要 | あり |
| `VALIDATION_INVALID_IP` | validation | Invalid IP address | warning | 要 | あり |
| `VALIDATION_CANNOT_SET_IP` | validation | Cannot set IP address | error | 要 | あり |
| `VALIDATION_OSC_PORT_INVALID` | validation | OSC port must be a number | warning | 要 | あり |
| `VALIDATION_CONFIG_VALUE_INVALID` | validation | The provided value was rejected | warning | 要 | あり |
| `AUTH_DEEPL_LENGTH` | auth | DeepL auth key length is not correct | warning | 要 | あり |
| `AUTH_DEEPL_FAILED` | auth | Authentication failure of deepL auth key | error | 要 | あり |
| `AUTH_PLAMO_LENGTH` | auth | Plamo auth key length is not correct | warning | 要 | あり |
| `AUTH_PLAMO_FAILED` | auth | Authentication failure of plamo auth key | error | 要 | あり |
| `AUTH_GEMINI_LENGTH` | auth | Gemini auth key length is not correct | warning | 要 | あり |
| `AUTH_GEMINI_FAILED` | auth | Authentication failure of gemini auth key | error | 要 | あり |
| `AUTH_OPENAI_INVALID` | auth | OpenAI auth key is not valid | warning | 要 | あり |
| `AUTH_OPENAI_FAILED` | auth | Authentication failure of OpenAI auth key | error | 要 | あり |
| `AUTH_OPENAI_COMPATIBLE_INVALID` | auth | OpenAI-compatible auth key is not valid | warning | 要 | あり |
| `AUTH_OPENAI_COMPATIBLE_FAILED` | auth | Authentication failure of OpenAI-compatible endpoint (check URL and auth key) | error | 要 | あり |
| `AUTH_GROQ_INVALID` | auth | Groq auth key is not valid | warning | 要 | あり |
| `AUTH_GROQ_FAILED` | auth | Authentication failure of Groq auth key | error | 要 | あり |
| `AUTH_OPENROUTER_INVALID` | auth | OpenRouter auth key is not valid | warning | 要 | あり |
| `AUTH_OPENROUTER_FAILED` | auth | Authentication failure of OpenRouter auth key | error | 要 | あり |
| `MODEL_PLAMO_INVALID` | model | Plamo model is not valid | warning | 要 | あり |
| `MODEL_GEMINI_INVALID` | model | Gemini model is not valid | warning | 要 | あり |
| `MODEL_OPENAI_INVALID` | model | OpenAI model is not valid | warning | 要 | あり |
| `MODEL_OPENAI_COMPATIBLE_INVALID` | model | OpenAI-compatible model is not valid | warning | 要 | あり |
| `MODEL_GROQ_INVALID` | model | Groq model is not valid | warning | 要 | あり |
| `MODEL_OPENROUTER_INVALID` | model | OpenRouter model is not valid | warning | 要 | あり |
| `MODEL_LMSTUDIO_INVALID` | model | LMStudio model is not valid | warning | 要 | あり |
| `MODEL_OLLAMA_INVALID` | model | ollama model is not valid | warning | 要 | あり |
| `MODEL_TRANSCRIPTION_INVALID` | model | Transcription API model is not valid | warning | 要 | あり |
| `CONNECTION_LMSTUDIO_FAILED` | connection | Cannot connect to LMStudio server | error | 要 | あり |
| `CONNECTION_OLLAMA_FAILED` | connection | Cannot connect to ollama server | error | 要 | あり |
| `CONNECTION_LMSTUDIO_URL_INVALID` | connection | LMStudio URL is not valid | warning | 要 | あり |
| `CONNECTION_OPENAI_COMPATIBLE_URL_INVALID` | connection | OpenAI-compatible endpoint URL is not valid | warning | 要 | あり |
| `CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID` | connection | Custom transcription server URL is not valid | warning | 要 | あり |
| `WEBSOCKET_HOST_INVALID` | websocket | WebSocket server host is not available | error | 要 | あり |
| `WEBSOCKET_PORT_UNAVAILABLE` | websocket | WebSocket server port is not available | error | 要 | あり |
| `WEBSOCKET_PORT_INVALID` | websocket | WebSocket server port must be a number | warning | 要 | あり |
| `WEBSOCKET_SERVER_UNAVAILABLE` | websocket | WebSocket server host or port is not available | error | 要 | あり |
| `OBS_BROWSER_SOURCE_HOST_UNAVAILABLE` | obs_browser_source | OBS Browser Source server host is not available | error | 要 | あり |
| `OBS_BROWSER_SOURCE_PORT_UNAVAILABLE` | obs_browser_source | OBS Browser Source server port is not available | error | 要 | あり |
| `OBS_BROWSER_SOURCE_PORT_INVALID` | obs_browser_source | OBS Browser Source port must be a number | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_SERVER_UNAVAILABLE` | obs_browser_source | OBS Browser Source server is not available | error | 要 | あり |
| `OBS_BROWSER_SOURCE_FONT_COLOR_INVALID` | obs_browser_source | OBS Browser Source font color is not valid (#RRGGBB) | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR_INVALID` | obs_browser_source | OBS Browser Source outline color is not valid (#RRGGBB) | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_MAX_MESSAGES_INVALID` | obs_browser_source | OBS Browser Source max messages must be a number | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_DISPLAY_DURATION_INVALID` | obs_browser_source | OBS Browser Source display duration must be a number | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_FADEOUT_DURATION_INVALID` | obs_browser_source | OBS Browser Source fadeout duration must be a number | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_FONT_SIZE_INVALID` | obs_browser_source | OBS Browser Source font size must be a number | warning | 要 | あり |
| `OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS_INVALID` | obs_browser_source | OBS Browser Source outline thickness must be a number | warning | 要 | あり |
| `VRC_MIC_MUTE_SYNC_OSC_DISABLED` | vrc | Cannot enable VRC mic mute sync while OSC query is disabled | warning | 要 | あり |
| `OCR_DISABLED_ENGINE_UNAVAILABLE` | ocr | OCR disabled: OCR engine or its dependencies are unavailable | error |  | あり |
| `OCR_DISABLED_MODEL_LOAD_FAILED` | ocr | OCR disabled: failed to load OCR model | error |  | あり |
| `OCR_DISABLED_UNSUPPORTED_LANGUAGE` | ocr | OCR disabled: source language is not supported | error |  | あり |
| `OCR_DISABLED_MODEL_MISSING` | ocr | OCR disabled: the OCR models for this language have not been downloaded | error | 要 | あり |
| `OCR_DISABLED_WINDOW_NOT_FOUND` | ocr | OCR disabled: the VRChat window was not found | error | 要 | あり |
| `OCR_DISABLED_CAPTURE_UNAVAILABLE` | ocr | OCR disabled: window capture is not available in this session | error | 要 | あり |
| `OCR_DISABLED_UNKNOWN` | ocr | OCR disabled due to an unknown error | error |  | あり |
| `GENERAL_EXCEPTION` | general | An error occurred | error |  | あり |
| `GENERAL_UNKNOWN` | general | Unknown error | error |  | あり |
