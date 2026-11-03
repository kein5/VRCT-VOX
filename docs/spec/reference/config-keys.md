<!-- 自動生成。手で編集しない。`python tools/spec_catalog.py --write`で更新する。 -->

# 設定キー一覧

`src-python/config.py`の`Config`クラス（`ManagedProperty`と`ValidatedProperty`）と`init_config()`の既定値から生成した。保存の仕組み（2秒の遅延、置き換えによる書き込み、読み込み時の検証）は[データ形式と保存](../data-and-persistence.md)にある。

## config.jsonに保存するキー（119件）

| キー | 型・検証 | 既定値 | 保存 |
|---|---|---|---|
| `ENABLE_FOREGROUND` | bool | `False` | 2秒後にまとめて |
| `CONVERT_MESSAGE_TO_ROMAJI` | bool | `False` | 2秒後にまとめて |
| `CONVERT_MESSAGE_TO_HIRAGANA` | bool | `False` | 2秒後にまとめて |
| `MAIN_WINDOW_SIDEBAR_COMPACT_MODE` | bool | `False` | 2秒後にまとめて |
| `TRANSPARENCY` | int | `100` | 2秒後にまとめて |
| `UI_SCALING` | int | `100` | 2秒後にまとめて |
| `TEXTBOX_UI_SCALING` | int | `100` | 2秒後にまとめて |
| `MESSAGE_BOX_RATIO` | (int, float) | `10` | 即時 |
| `SEND_MESSAGE_BUTTON_TYPE` | str、許可値 lambda v, inst: v in inst.SEND_MESSAGE_BUTTON_TYPE_LIST | `'show'` | 2秒後にまとめて |
| `SHOW_RESEND_BUTTON` | bool | `False` | 2秒後にまとめて |
| `FONT_FAMILY` | str | `'Yu Gothic UI'` | 2秒後にまとめて |
| `UI_LANGUAGE` | str、許可値 lambda v, inst: v in inst.SELECTABLE_UI_LANGUAGE_LIST | `'en'` | 2秒後にまとめて |
| `MAIN_WINDOW_GEOMETRY` | 検証 _main_window_geometry_validator | `{'x_pos': 0, 'y_pos': 0, 'width': 870, 'height': 654}` | 即時 |
| `MIC_THRESHOLD` | int | `300` | 2秒後にまとめて |
| `MIC_AUTOMATIC_THRESHOLD` | bool | `False` | 2秒後にまとめて |
| `MIC_RECORD_TIMEOUT` | int | `3` | 2秒後にまとめて |
| `MIC_PHRASE_TIMEOUT` | int | `3` | 2秒後にまとめて |
| `MIC_MAX_PHRASES` | int | `10` | 2秒後にまとめて |
| `MIC_AVG_LOGPROB` | (int, float) | `-0.8` | 2秒後にまとめて |
| `MIC_NO_SPEECH_PROB` | (int, float) | `0.6` | 2秒後にまとめて |
| `MIC_NO_REPEAT_NGRAM_SIZE` | int | `0` | 2秒後にまとめて |
| `HOTKEYS` | 検証 lambda val, inst: {**inst.HOTKEYS, **{k: v if isinstance(v, list) or v is None else inst.HOTKEYS.get(k) for k, v in val.items()}} if isinstance(val, dict) and set(val.keys()) <= set(inst.HOTKEYS.keys()) else None | `{'open_quick_chat': None, 'toggle_vrct_visibility': None, 'toggle_translation': None, '…` | 即時 |
| `SPEAKER_THRESHOLD` | int | `300` | 2秒後にまとめて |
| `SPEAKER_AUTOMATIC_THRESHOLD` | bool | `False` | 2秒後にまとめて |
| `SPEAKER_RECORD_TIMEOUT` | int | `3` | 2秒後にまとめて |
| `SPEAKER_PHRASE_TIMEOUT` | int | `3` | 2秒後にまとめて |
| `SPEAKER_MAX_PHRASES` | int | `10` | 2秒後にまとめて |
| `SPEAKER_AVG_LOGPROB` | (int, float) | `-0.8` | 2秒後にまとめて |
| `SPEAKER_NO_SPEECH_PROB` | (int, float) | `0.6` | 2秒後にまとめて |
| `SPEAKER_NO_REPEAT_NGRAM_SIZE` | int | `0` | 2秒後にまとめて |
| `MIC_ENABLE_VAD` | bool | `False` | 2秒後にまとめて |
| `SPEAKER_ENABLE_VAD` | bool | `False` | 2秒後にまとめて |
| `AUTH_KEYS` | 検証 lambda val, inst: {k: val[k] if k in val and isinstance(val[k], (str, type(None))) else inst.AUTH_KEYS.get(k) for k in inst.AUTH_KEYS.keys()} if isinstance(val, dict) else None | `{'DeepL_API': None, 'Plamo_API': None, 'Gemini_API': None, 'OpenAI_API': None, 'OpenAI_…` | 2秒後にまとめて |
| `LMSTUDIO_URL` | str | `'http://127.0.0.1:1234/v1'` | 2秒後にまとめて |
| `OPENAI_COMPATIBLE_URL` | str | `'https://api.openai.com/v1'` | 2秒後にまとめて |
| `TRANSCRIPTION_AUTH_KEYS` | 検証 lambda val, inst: {k: val[k] if k in val and isinstance(val[k], (str, type(None))) else inst.TRANSCRIPTION_AUTH_KEYS.get(k) for k in inst.TRANSCRIPTION_AUTH_KEYS.keys()} if isinstance(val, dict) else None | `{'Groq_Whisper': None, 'OpenAI_Whisper': None, 'Custom_Whisper': None, 'Deepgram': None}` | 2秒後にまとめて |
| `TRANSCRIPTION_CUSTOM_URL` | str | `''` | 2秒後にまとめて |
| `SELECTED_TRANSCRIPTION_COMPUTE_TYPE` | 検証 _selected_transcription_compute_type_validator | `'auto'` | 2秒後にまとめて |
| `OVERLAY_SMALL_LOG_SETTINGS` | 検証 _overlay_small_validator | `{'x_pos': 0.0, 'y_pos': 0.0, 'z_pos': 0.0, 'x_rotation': 0.0, 'y_rotation': 0.0, 'z_rot…` | 2秒後にまとめて |
| `OVERLAY_LARGE_LOG_SETTINGS` | 検証 _overlay_large_validator | `{'x_pos': 0.0, 'y_pos': 0.0, 'z_pos': 0.0, 'x_rotation': 0.0, 'y_rotation': 0.0, 'z_rot…` | 2秒後にまとめて |
| `OVERLAY_VR_PANEL_SETTINGS` | 検証 _make_overlay_vr_window_validator('OVERLAY_VR_PANEL_SETTINGS') | `{'width': 900, 'height': 700, 'x_pos': 0.5209, 'y_pos': 0.6442, 'z_pos': -0.9509, 'x_ro…` | 2秒後にまとめて |
| `OVERLAY_VR_LAUNCHER_SETTINGS` | 検証 _make_overlay_vr_window_validator('OVERLAY_VR_LAUNCHER_SETTINGS') | `dict(DEFAULT_OVERLAY_VR_LAUNCHER_SETTINGS)` | 2秒後にまとめて |
| `SEND_MESSAGE_FORMAT_PARTS` | 検証 _format_validator_send | `{'message': {'prefix': '', 'suffix': ''}, 'separator': '\n', 'translation': {'prefix': …` | 2秒後にまとめて |
| `RECEIVED_MESSAGE_FORMAT_PARTS` | 検証 _format_validator_received | `{'message': {'prefix': '', 'suffix': ''}, 'separator': '\n', 'translation': {'prefix': …` | 2秒後にまとめて |
| `VOICE_SETTINGS` | 検証 normalize_settings | `VoiceSettings().to_dict()` | 2秒後にまとめて |
| `DIRECT_VOICE_SETTINGS` | 検証 normalize_direct_settings | `DirectSettings().to_dict()` | 2秒後にまとめて |
| `REALTIME_ASR_SETTINGS` | 検証 lambda value, instance: normalize_realtime_settings(value) | `normalize_realtime_settings({})` | 2秒後にまとめて |
| `SPEECH_SERVER_SETTINGS` | 検証 lambda value, instance: normalize_speech_server_settings(value) | `normalize_speech_server_settings({})` | 2秒後にまとめて |
| `WEBSOCKET_SERVER` | bool | `False` | 2秒後にまとめて |
| `OSC_IP_ADDRESS` | str | `'127.0.0.1'` | 2秒後にまとめて |
| `OSC_PORT` | int | `9000` | 2秒後にまとめて |
| `AUTO_CLEAR_MESSAGE_BOX` | bool | `True` | 2秒後にまとめて |
| `SEND_ONLY_TRANSLATED_MESSAGES` | bool | `False` | 2秒後にまとめて |
| `OVERLAY_SMALL_LOG` | bool | `False` | 2秒後にまとめて |
| `OVERLAY_LARGE_LOG` | bool | `False` | 2秒後にまとめて |
| `OVERLAY_VR_PANEL` | bool | `False` | 2秒後にまとめて |
| `OVERLAY_VR_PANEL_LOCKED` | bool | `False` | 2秒後にまとめて |
| `OVERLAY_VR_PANEL_FONT_SIZE` | int | `17` | 2秒後にまとめて |
| `OVERLAY_VR_LAUNCHER_AUTO_HIDE` | bool | `True` | 2秒後にまとめて |
| `OVERLAY_VR_TOOLTIP` | bool | `True` | 2秒後にまとめて |
| `OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES` | bool | `False` | 2秒後にまとめて |
| `SEND_MESSAGE_TO_VRC` | bool | `True` | 2秒後にまとめて |
| `SEND_RECEIVED_MESSAGE_TO_VRC` | bool | `False` | 2秒後にまとめて |
| `LOGGER_FEATURE` | bool | `False` | 2秒後にまとめて |
| `VRC_MIC_MUTE_SYNC` | bool | `False` | 2秒後にまとめて |
| `NOTIFICATION_VRC_SFX` | bool | `True` | 2秒後にまとめて |
| `WEBSOCKET_HOST` | str、許可値 lambda v, inst: isValidIpAddress(v) and (not isWildcardBindAddress(v)) | `'127.0.0.1'` | 2秒後にまとめて |
| `WEBSOCKET_PORT` | int | `2231` | 2秒後にまとめて |
| `WEBSOCKET_AUTH_TOKEN` | str | `secrets_token_urlsafe(32)` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE` | bool | `False` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_PORT` | int | `2232` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_MAX_MESSAGES` | int | `14` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_DISPLAY_DURATION` | int | `60` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_FADEOUT_DURATION` | int | `12` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_FONT_SIZE` | int | `40` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_FONT_COLOR` | str | `'#FFFFFF'` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_FONT_OUTLINE_THICKNESS` | int | `3` | 2秒後にまとめて |
| `OBS_BROWSER_SOURCE_FONT_OUTLINE_COLOR` | str | `'#000000'` | 2秒後にまとめて |
| `ENABLE_TELEMETRY` | bool | `False` | 2秒後にまとめて |
| `AUTO_DOWNLOAD_MODELS` | bool | `False` | 2秒後にまとめて |
| `SELECTED_TAB_NO` | str、許可値 lambda v, inst: v in inst.SELECTABLE_TAB_NO_LIST | `'1'` | 2秒後にまとめて |
| `SELECTED_TRANSCRIPTION_ENGINE` | str、許可値 lambda v, inst: v in inst.SELECTABLE_TRANSCRIPTION_ENGINE_LIST | `'Google'` | 2秒後にまとめて |
| `SELECTED_RELEASE_CHANNEL` | str、許可値 lambda v, inst: v in inst.SELECTABLE_RELEASE_CHANNEL_LIST | `'stable'` | 2秒後にまとめて |
| `CTRANSLATE2_WEIGHT_TYPE` | str、許可値 lambda v, inst: v in inst.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST | `DEFAULT_CTRANSLATE2_WEIGHT_TYPE` | 2秒後にまとめて |
| `CTRANSLATE2_LICENSE_NOTICE_SHOWN` | bool | `False` | 2秒後にまとめて |
| `WHISPER_WEIGHT_TYPE` | str、許可値 lambda v, inst: v in inst.SELECTABLE_WHISPER_WEIGHT_TYPE_LIST | `'base'` | 2秒後にまとめて |
| `SELECTED_PLAMO_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_PLAMO_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_GEMINI_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_GEMINI_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_OPENAI_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_OPENAI_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_GROQ_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_GROQ_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_OPENROUTER_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_OPENROUTER_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_LMSTUDIO_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_LMSTUDIO_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_OPENAI_COMPATIBLE_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_OLLAMA_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_OLLAMA_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_GROQ_WHISPER_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_GROQ_WHISPER_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_OPENAI_WHISPER_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_OPENAI_WHISPER_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_CUSTOM_WHISPER_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_CUSTOM_WHISPER_MODEL_LIST') | `None` | 2秒後にまとめて |
| `SELECTED_DEEPGRAM_MODEL` | str、許可値 _allowed_in_populated('SELECTABLE_DEEPGRAM_MODEL_LIST') | `None` | 2秒後にまとめて |
| `MIC_WORD_FILTER` | 検証 _mic_word_filter_validator | `[]` | 2秒後にまとめて |
| `SELECTED_TRANSLATION_ENGINES` | 検証 _selected_translation_engines_validator | `{}` | 2秒後にまとめて |
| `SELECTED_YOUR_LANGUAGES` | 検証 _selected_your_languages_validator | `{}` | 2秒後にまとめて |
| `SELECTED_TARGET_LANGUAGES` | 検証 _selected_target_languages_validator | `{}` | 2秒後にまとめて |
| `SELECTED_TRANSLATION_COMPUTE_TYPE` | 検証 _selected_translation_compute_type_validator | `'auto'` | 2秒後にまとめて |
| `AUTO_MIC_SELECT` | bool | `True` | 2秒後にまとめて |
| `AUTO_SPEAKER_SELECT` | bool | `True` | 2秒後にまとめて |
| `SELECTED_MIC_HOST` | 検証 _mic_host_validator | `dm_def.get('host', {}).get('name', 'NoHost')` | 2秒後にまとめて |
| `SELECTED_MIC_DEVICE` | 検証 _mic_device_validator | `dm_def.get('device', {}).get('name', 'NoDevice')` | 2秒後にまとめて |
| `SELECTED_SPEAKER_DEVICE` | 検証 _speaker_device_validator | `sp_def.get('device', {}).get('name', 'NoDevice')` | 2秒後にまとめて |
| `SELECTED_TRANSLATION_COMPUTE_DEVICE` | 検証 _compute_device_validator | `copy.deepcopy(self.SELECTABLE_COMPUTE_DEVICE_LIST[0])` | 2秒後にまとめて |
| `SELECTED_TRANSCRIPTION_COMPUTE_DEVICE` | 検証 _compute_device_validator | `copy.deepcopy(self.SELECTABLE_COMPUTE_DEVICE_LIST[0])` | 2秒後にまとめて |
| `ENABLE_CLIPBOARD` | bool | `False` | 2秒後にまとめて |
| `OCR_SOURCE_LANGUAGE` | str、許可値 lambda v, inst: v in inst.SELECTABLE_OCR_SOURCE_LANGUAGE_LIST | `'auto'` | 2秒後にまとめて |
| `OCR_WINDOW_TITLE` | str、許可値 lambda v, inst: len(v) > 0 | `'VRChat'` | 2秒後にまとめて |
| `OCR_POLL_INTERVAL_MS` | int、許可値 lambda v, inst: 100 <= v <= 5000 | `750` | 2秒後にまとめて |
| `OCR_MIN_CONFIDENCE` | (int, float)、許可値 lambda v, inst: 0.1 <= v <= 0.99 | `0.85` | 2秒後にまとめて |
| `OCR_BUBBLE_MIN_TEXT_LENGTH` | int、許可値 lambda v, inst: 1 <= v <= 50 | `2` | 2秒後にまとめて |
| `OCR_CAPTURE_REGION` | dict、許可値 _ocr_capture_region_validator | `{'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 1.0}` | 2秒後にまとめて |
| `OCR_CHATBOX_FILTER` | bool | `True` | 2秒後にまとめて |
| `OCR_USE_CHATBOX_DETECTOR` | bool | `True` | 2秒後にまとめて |


## 保存しないキー（47件）

実行中だけの状態、選択肢の一覧、読み取り専用の値。起動のたびに既定値や検出結果から作り直す。

| キー | 型・検証 | 既定値 | 扱い |
|---|---|---|---|
| `VERSION` |  | `'0.1.0-beta.4'` | 読み取り専用 |
| `PATH_LOCAL` |  | `os_path.dirname(sys.executable)` | 読み取り専用 |
| `PATH_DATA` |  | `str(data_root(self._PATH_LOCAL))` | 読み取り専用 |
| `PATH_CONFIG` |  | `os_path.join(state_dir, 'config.json')` | 読み取り専用 |
| `PATH_LOGS` |  | `os_path.join(state_dir, 'logs')` | 読み取り専用 |
| `GITHUB_URL` |  | `'https://api.github.com/repos/kein5/VRCT-VOX/releases/latest'` | 読み取り専用 |
| `GITHUB_RELEASES_LIST_URL` |  | `'https://api.github.com/repos/kein5/VRCT-VOX/releases'` | 読み取り専用 |
| `MIN_SUPPORTED_VERSION` |  | `'0.1.0'` | 読み取り専用 |
| `SELECTABLE_RELEASE_CHANNEL_LIST` |  | `['stable', 'beta']` | 読み取り専用 |
| `MAX_MIC_THRESHOLD` |  | `2000` | 読み取り専用 |
| `MAX_SPEAKER_THRESHOLD` |  | `2000` | 読み取り専用 |
| `WATCHDOG_TIMEOUT` |  | `60` | 読み取り専用 |
| `WATCHDOG_INTERVAL` |  | `20` | 読み取り専用 |
| `SELECTABLE_TAB_NO_LIST` |  | `['1', '2', '3']` | 読み取り専用 |
| `SELECTED_TAB_TARGET_LANGUAGES_NO_LIST` |  | `['1', '2', '3']` | 読み取り専用 |
| `SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_LIST` |  | `getattr(ctranslate2_weights, 'keys', lambda: [])()` | 読み取り専用 |
| `SELECTABLE_WHISPER_WEIGHT_TYPE_LIST` |  | `getattr(whisper_models, 'keys', lambda: [])()` | 読み取り専用 |
| `SELECTABLE_TRANSLATION_ENGINE_LIST` |  | `getattr(translation_lang, 'keys', lambda: [])()` | 読み取り専用 |
| `SELECTABLE_TRANSCRIPTION_ENGINE_LIST` |  | `list(transcription_lang[first_key].values())[0].keys()` | 読み取り専用 |
| `SELECTABLE_UI_LANGUAGE_LIST` |  | `['en', 'ja', 'ko', 'zh-Hant', 'zh-Hans']` | 読み取り専用 |
| `SELECTABLE_OCR_SOURCE_LANGUAGE_LIST` |  | `list(ocr_selectable_languages)` | 読み取り専用 |
| `COMPUTE_MODE` |  | `'cuda' if any((device.get('device') == 'cuda' for device in self._SELECTABLE_COMPUTE_DE…` | 読み取り専用 |
| `SELECTABLE_COMPUTE_DEVICE_LIST` |  | `getComputeDeviceList()` | 読み取り専用 |
| `SEND_MESSAGE_BUTTON_TYPE_LIST` |  | `['show', 'hide', 'show_and_disable_enter_key']` | 読み取り専用 |
| `ENABLE_TRANSLATION` | bool | `False` | 保存しない |
| `ENABLE_TRANSCRIPTION_SEND` | bool | `False` | 保存しない |
| `ENABLE_TRANSCRIPTION_RECEIVE` | bool | `False` | 保存しない |
| `ENABLE_OCR_CAPTURE` | bool | `False` | 保存しない |
| `ENABLE_CHECK_ENERGY_SEND` | bool | `False` | 保存しない |
| `ENABLE_CHECK_ENERGY_RECEIVE` | bool | `False` | 保存しない |
| `SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT` | dict | `{}` | 保存しない |
| `SELECTABLE_WHISPER_WEIGHT_TYPE_DICT` | dict | `{}` | 保存しない |
| `SELECTABLE_TRANSLATION_ENGINE_STATUS` | dict | `{}` | 保存しない |
| `SELECTABLE_TRANSCRIPTION_ENGINE_STATUS` | dict | `{}` | 保存しない |
| `SELECTABLE_PLAMO_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_GEMINI_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_OPENAI_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_GROQ_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_OPENROUTER_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_LMSTUDIO_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_OPENAI_COMPATIBLE_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_OLLAMA_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_GROQ_WHISPER_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_OPENAI_WHISPER_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_CUSTOM_WHISPER_MODEL_LIST` | list | `[]` | 保存しない |
| `SELECTABLE_DEEPGRAM_MODEL_LIST` | list | `[]` | 保存しない |
| `DEEPGRAM_MODEL_LANGUAGES` | dict | `{}` | 保存しない |
