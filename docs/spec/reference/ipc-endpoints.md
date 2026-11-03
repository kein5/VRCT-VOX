<!-- 自動生成。手で編集しない。`python tools/spec_catalog.py --write`で更新する。 -->

# IPCエンドポイント一覧

UIからサイドカーへの要求（`mapping`）と、サイドカーからUIへの通知（`run_mapping`）の一覧。メッセージの形、状態コード、ロックと再試行の規則は[IPCプロトコル](../ipc-protocol.md)にある。

列の意味:

- 初期化前: 「待つ」は初期化が終わるまでロックされる要求（サイドカーが約30秒まで入れ直し、解けなければ423を返す）。「可」は起動直後から受け付ける。
- UIの受信先: 200の応答を処理するUIのフック（`useReceiveRoutes.js`の静的ルートと`ui_config_setter.js`の定義から生成）。「—」は受信先がない。
- ログで伏せる: `process.log`で値を`***MASKED***`に置き換える（`SENSITIVE_ENDPOINT_MARKERS`）。stdoutのIPCそのものは伏せない。

## 要求（384件: 削除 11、取得 169、実行 35、有効化 38、無効化 38、設定 93）

| エンドポイント | 種別 | 処理（controller） | 初期化前 | UIの受信先 | 備考 |
|---|---|---|---|---|---|
| `/set/enable/translation` | 有効化 | `setEnableTranslation` | 待つ | useMainFunction.updateTranslationStatus |  |
| `/set/disable/translation` | 無効化 | `setDisableTranslation` | 待つ | useMainFunction.updateTranslationStatus |  |
| `/set/enable/transcription_send` | 有効化 | `setEnableTranscriptionSend` | 待つ | useMainFunction.updateTranscriptionSendStatus |  |
| `/set/disable/transcription_send` | 無効化 | `setDisableTranscriptionSend` | 待つ | useMainFunction.updateTranscriptionSendStatus |  |
| `/set/enable/transcription_receive` | 有効化 | `setEnableTranscriptionReceive` | 待つ | useMainFunction.updateTranscriptionReceiveStatus |  |
| `/set/disable/transcription_receive` | 無効化 | `setDisableTranscriptionReceive` | 待つ | useMainFunction.updateTranscriptionReceiveStatus |  |
| `/set/enable/ocr_capture` | 有効化 | `setEnableOcrCapture` | 待つ | useMainFunction.updateOcrCaptureStatus |  |
| `/set/disable/ocr_capture` | 無効化 | `setDisableOcrCapture` | 待つ | useMainFunction.updateOcrCaptureStatus |  |
| `/get/data/foreground` | 取得 | `getEnableForeground` | 可 | useMainFunction.restoreForeground |  |
| `/set/enable/foreground` | 有効化 | `setEnableForeground` | 可 | useMainFunction.updateForegroundStatus |  |
| `/set/disable/foreground` | 無効化 | `setDisableForeground` | 可 | useMainFunction.updateForegroundStatus |  |
| `/get/data/selected_tab_no` | 取得 | `getSelectedTabNo` | 可 | useLanguageSettings.updateSelectedPresetTabNumber |  |
| `/set/data/selected_tab_no` | 設定 | `setSelectedTabNo` | 可 | useLanguageSettings.updateSelectedPresetTabNumber |  |
| `/get/data/main_window_sidebar_compact_mode` | 取得 | `getMainWindowSidebarCompactMode` | 可 | useIsMainPageCompactMode.updateIsMainPageCompactMode |  |
| `/set/enable/main_window_sidebar_compact_mode` | 有効化 | `setEnableMainWindowSidebarCompactMode` | 可 | useIsMainPageCompactMode.updateIsMainPageCompactMode |  |
| `/set/disable/main_window_sidebar_compact_mode` | 無効化 | `setDisableMainWindowSidebarCompactMode` | 可 | useIsMainPageCompactMode.updateIsMainPageCompactMode |  |
| `/get/data/selectable_translation_engines` | 取得 | `getTranslationEngines` | 可 | useLanguageSettings.updateTranslatorAvailability |  |
| `/get/data/selectable_language_list` | 取得 | `getListLanguageAndCountry` | 可 | useLanguageSettings.updateSelectableLanguageList |  |
| `/get/data/selected_translation_engines` | 取得 | `getSelectedTranslationEngines` | 待つ | useLanguageSettings.updateSelectedTranslationEngines |  |
| `/set/data/selected_translation_engines` | 設定 | `setSelectedTranslationEngines` | 可 | useLanguageSettings.updateSelectedTranslationEngines |  |
| `/get/data/selected_your_languages` | 取得 | `getSelectedYourLanguages` | 可 | useLanguageSettings.updateSelectedYourLanguages |  |
| `/set/data/selected_your_languages` | 設定 | `setSelectedYourLanguages` | 可 | useLanguageSettings.updateSelectedYourLanguages |  |
| `/get/data/selected_target_languages` | 取得 | `getSelectedTargetLanguages` | 可 | useLanguageSettings.updateSelectedTargetLanguages |  |
| `/set/data/selected_target_languages` | 設定 | `setSelectedTargetLanguages` | 可 | useLanguageSettings.updateSelectedTargetLanguages |  |
| `/get/data/selectable_transcription_engines` | 取得 | `getTranscriptionEngines` | 待つ | useTranscription.updateFromBackendSelectableTranscriptionEngines |  |
| `/get/data/selected_transcription_engine` | 取得 | `getSelectedTranscriptionEngine` | 待つ | useTranscription.updateFromBackendSelectedTranscriptionEngine |  |
| `/set/data/selected_transcription_engine` | 設定 | `setSelectedTranscriptionEngine` | 待つ | useTranscription.setSuccessSelectedTranscriptionEngine |  |
| `/get/data/groq_whisper_auth_key` | 取得 | `getGroqWhisperAuthKey` | 可 | useTranscription.updateFromBackendGroqWhisperAuthKey | ログで伏せる |
| `/set/data/groq_whisper_auth_key` | 設定 | `setGroqWhisperAuthKey` | 可 | useTranscription.setSuccessGroqWhisperAuthKey | ログで伏せる |
| `/delete/data/groq_whisper_auth_key` | 削除 | `delGroqWhisperAuthKey` | 可 | useTranscription.deleteSuccessGroqWhisperAuthKey | ログで伏せる |
| `/get/data/selectable_groq_whisper_model_list` | 取得 | `getGroqWhisperModelList` | 可 | useTranscription.updateFromBackendSelectableGroqWhisperModelList |  |
| `/get/data/selected_groq_whisper_model` | 取得 | `getGroqWhisperModel` | 可 | useTranscription.updateFromBackendSelectedGroqWhisperModel |  |
| `/set/data/selected_groq_whisper_model` | 設定 | `setGroqWhisperModel` | 可 | useTranscription.setSuccessSelectedGroqWhisperModel |  |
| `/get/data/openai_whisper_auth_key` | 取得 | `getOpenAIWhisperAuthKey` | 可 | useTranscription.updateFromBackendOpenAIWhisperAuthKey | ログで伏せる |
| `/set/data/openai_whisper_auth_key` | 設定 | `setOpenAIWhisperAuthKey` | 可 | useTranscription.setSuccessOpenAIWhisperAuthKey | ログで伏せる |
| `/delete/data/openai_whisper_auth_key` | 削除 | `delOpenAIWhisperAuthKey` | 可 | useTranscription.deleteSuccessOpenAIWhisperAuthKey | ログで伏せる |
| `/get/data/selectable_openai_whisper_model_list` | 取得 | `getOpenAIWhisperModelList` | 可 | useTranscription.updateFromBackendSelectableOpenAIWhisperModelList |  |
| `/get/data/selected_openai_whisper_model` | 取得 | `getOpenAIWhisperModel` | 可 | useTranscription.updateFromBackendSelectedOpenAIWhisperModel |  |
| `/set/data/selected_openai_whisper_model` | 設定 | `setOpenAIWhisperModel` | 可 | useTranscription.setSuccessSelectedOpenAIWhisperModel |  |
| `/get/data/custom_whisper_auth_key` | 取得 | `getCustomWhisperAuthKey` | 可 | useTranscription.updateFromBackendCustomWhisperAuthKey | ログで伏せる |
| `/set/data/custom_whisper_auth_key` | 設定 | `setCustomWhisperAuthKey` | 可 | useTranscription.setSuccessCustomWhisperAuthKey | ログで伏せる |
| `/delete/data/custom_whisper_auth_key` | 削除 | `delCustomWhisperAuthKey` | 可 | useTranscription.deleteSuccessCustomWhisperAuthKey | ログで伏せる |
| `/get/data/custom_whisper_url` | 取得 | `getCustomWhisperURL` | 可 | useTranscription.updateFromBackendCustomWhisperURL |  |
| `/set/data/custom_whisper_url` | 設定 | `setCustomWhisperURL` | 可 | useTranscription.setSuccessCustomWhisperURL |  |
| `/get/data/selectable_custom_whisper_model_list` | 取得 | `getCustomWhisperModelList` | 可 | useTranscription.updateFromBackendSelectableCustomWhisperModelList |  |
| `/get/data/selected_custom_whisper_model` | 取得 | `getCustomWhisperModel` | 可 | useTranscription.updateFromBackendSelectedCustomWhisperModel |  |
| `/set/data/selected_custom_whisper_model` | 設定 | `setCustomWhisperModel` | 可 | useTranscription.setSuccessSelectedCustomWhisperModel |  |
| `/get/data/deepgram_auth_key` | 取得 | `getDeepgramAuthKey` | 可 | useTranscription.updateFromBackendDeepgramAuthKey | ログで伏せる |
| `/set/data/deepgram_auth_key` | 設定 | `setDeepgramAuthKey` | 可 | useTranscription.setSuccessDeepgramAuthKey | ログで伏せる |
| `/delete/data/deepgram_auth_key` | 削除 | `delDeepgramAuthKey` | 可 | useTranscription.deleteSuccessDeepgramAuthKey | ログで伏せる |
| `/get/data/selectable_deepgram_model_list` | 取得 | `getDeepgramModelList` | 可 | useTranscription.updateFromBackendSelectableDeepgramModelList |  |
| `/get/data/selected_deepgram_model` | 取得 | `getDeepgramModel` | 可 | useTranscription.updateFromBackendSelectedDeepgramModel |  |
| `/set/data/selected_deepgram_model` | 設定 | `setDeepgramModel` | 可 | useTranscription.setSuccessSelectedDeepgramModel |  |
| `/get/data/selectable_release_channels` | 取得 | `getSelectableReleaseChannels` | 可 | （受け取るだけ） |  |
| `/get/data/release_channel` | 取得 | `getSelectedReleaseChannel` | 可 | useUpdater.updateFromBackendReleaseChannel |  |
| `/set/data/release_channel` | 設定 | `setSelectedReleaseChannel` | 可 | useUpdater.setSuccessReleaseChannel |  |
| `/get/data/available_releases` | 取得 | `listAvailableReleases` | 可 | useAvailableReleases.updateAvailableReleasesFromBackend |  |
| `/run/send_message_box` | 実行 | `sendMessageBox` | 待つ | useMessage.updateSentMessageLogById |  |
| `/run/typing_message_box` | 実行 | `typingMessageBox` | 待つ | （受け取るだけ） |  |
| `/run/stop_typing_message_box` | 実行 | `stopTypingMessageBox` | 待つ | （受け取るだけ） |  |
| `/run/send_text_overlay` | 実行 | `sendTextOverlay` | 可 | （受け取るだけ） |  |
| `/get/data/telemetry` | 取得 | `getTelemetry` | 可 | useOthers.updateFromBackendTelemetry |  |
| `/get/data/auto_download_models` | 取得 | `getAutoDownloadModels` | 可 | useOthers.updateFromBackendAutoDownloadModels |  |
| `/set/enable/auto_download_models` | 有効化 | `setEnableAutoDownloadModels` | 可 | useOthers.setSuccessAutoDownloadModels |  |
| `/set/disable/auto_download_models` | 無効化 | `setDisableAutoDownloadModels` | 可 | useOthers.setSuccessAutoDownloadModels |  |
| `/set/enable/telemetry` | 有効化 | `setEnableTelemetry` | 可 | useOthers.setSuccessTelemetry |  |
| `/set/disable/telemetry` | 無効化 | `setDisableTelemetry` | 可 | useOthers.setSuccessTelemetry |  |
| `/run/shutdown` | 実行 | `shutdown` | 可 | （受け取るだけ） |  |
| `/run/swap_your_language_and_target_language` | 実行 | `swapYourLanguageAndTargetLanguage` | 可 | useLanguageSettings.updateBothSelectedLanguages |  |
| `/run/update_software` | 実行 | `updateSoftware` | 可 | （受け取るだけ） |  |
| `/run/update_cuda_software` | 実行 | `updateCudaSoftware` | 可 | （受け取るだけ） |  |
| `/get/data/version` | 取得 | `getVersion` | 可 | useSoftwareVersion.updateSoftwareVersion |  |
| `/get/data/transparency` | 取得 | `getTransparency` | 可 | useAppearance.updateFromBackendTransparency |  |
| `/set/data/transparency` | 設定 | `setTransparency` | 可 | useAppearance.setSuccessTransparency |  |
| `/get/data/ui_scaling` | 取得 | `getUiScaling` | 可 | useAppearance.updateFromBackendUiScaling |  |
| `/set/data/ui_scaling` | 設定 | `setUiScaling` | 可 | useAppearance.setSuccessUiScaling |  |
| `/get/data/textbox_ui_scaling` | 取得 | `getTextboxUiScaling` | 可 | useAppearance.updateFromBackendMessageLogUiScaling |  |
| `/set/data/textbox_ui_scaling` | 設定 | `setTextboxUiScaling` | 可 | useAppearance.setSuccessMessageLogUiScaling |  |
| `/get/data/message_box_ratio` | 取得 | `getMessageBoxRatio` | 可 | useMessageInputBoxRatio.updateMessageInputBoxRatio |  |
| `/set/data/message_box_ratio` | 設定 | `setMessageBoxRatio` | 可 | useMessageInputBoxRatio.updateMessageInputBoxRatio |  |
| `/get/data/send_message_button_type` | 取得 | `getSendMessageButtonType` | 可 | useAppearance.updateFromBackendSendMessageButtonType |  |
| `/set/data/send_message_button_type` | 設定 | `setSendMessageButtonType` | 可 | useAppearance.setSuccessSendMessageButtonType |  |
| `/get/data/show_resend_button` | 取得 | `getShowResendButton` | 可 | useAppearance.updateFromBackendShowResendButton |  |
| `/set/enable/show_resend_button` | 有効化 | `setEnableShowResendButton` | 可 | useAppearance.setSuccessShowResendButton |  |
| `/set/disable/show_resend_button` | 無効化 | `setDisableShowResendButton` | 可 | useAppearance.setSuccessShowResendButton |  |
| `/get/data/font_family` | 取得 | `getFontFamily` | 可 | useAppearance.updateFromBackendSelectedFontFamily |  |
| `/set/data/font_family` | 設定 | `setFontFamily` | 可 | useAppearance.setSuccessSelectedFontFamily |  |
| `/get/data/ui_language` | 取得 | `getUiLanguage` | 可 | useAppearance.updateFromBackendUiLanguage |  |
| `/set/data/ui_language` | 設定 | `setUiLanguage` | 可 | useAppearance.setSuccessUiLanguage |  |
| `/get/data/main_window_geometry` | 取得 | `getMainWindowGeometry` | 可 | useWindow.restoreWindowGeometry |  |
| `/set/data/main_window_geometry` | 設定 | `setMainWindowGeometry` | 可 | （受け取るだけ） |  |
| `/get/data/compute_mode` | 取得 | `getComputeMode` | 可 | useComputeMode.updateComputeMode |  |
| `/get/data/selectable_translation_compute_device_list` | 取得 | `getComputeDeviceList` | 可 | useTranslation.updateFromBackendSelectableTranslationComputeDeviceList |  |
| `/get/data/selected_translation_compute_device` | 取得 | `getSelectedTranslationComputeDevice` | 可 | useTranslation.updateFromBackendSelectedTranslationComputeDevice |  |
| `/set/data/selected_translation_compute_device` | 設定 | `setSelectedTranslationComputeDevice` | 可 | useTranslation.setSuccessSelectedTranslationComputeDevice |  |
| `/get/data/selectable_transcription_compute_device_list` | 取得 | `getComputeDeviceList` | 可 | useTranscription.updateFromBackendSelectableTranscriptionComputeDeviceList |  |
| `/get/data/selected_transcription_compute_device` | 取得 | `getSelectedTranscriptionComputeDevice` | 可 | useTranscription.updateFromBackendSelectedTranscriptionComputeDevice |  |
| `/set/data/selected_transcription_compute_device` | 設定 | `setSelectedTranscriptionComputeDevice` | 可 | useTranscription.setSuccessSelectedTranscriptionComputeDevice |  |
| `/get/data/selectable_ctranslate2_weight_type_dict` | 取得 | `getSelectableCtranslate2WeightTypeDict` | 可 | useTranslation.updateDownloadedCTranslate2WeightTypeStatus |  |
| `/get/data/selected_ctranslate2_weight_type` | 取得 | `getCtranslate2WeightType` | 可 | useTranslation.updateFromBackendSelectedCTranslate2WeightType |  |
| `/set/data/selected_ctranslate2_weight_type` | 設定 | `setCtranslate2WeightType` | 可 | useTranslation.setSuccessSelectedCTranslate2WeightType |  |
| `/get/data/selected_translation_compute_type` | 取得 | `getSelectedTranslationComputeType` | 可 | useTranslation.updateFromBackendSelectedTranslationComputeType |  |
| `/set/data/selected_translation_compute_type` | 設定 | `setSelectedTranslationComputeType` | 可 | useTranslation.setSuccessSelectedTranslationComputeType |  |
| `/run/download_ctranslate2_weight` | 実行 | `downloadCtranslate2Weight` | 可 | useTranslation.downloadedCTranslate2WeightTypeStatus |  |
| `/get/data/deepl_auth_key` | 取得 | `getDeepLAuthKey` | 待つ | useTranslation.updateFromBackendDeepLAuthKey | ログで伏せる |
| `/set/data/deepl_auth_key` | 設定 | `setDeeplAuthKey` | 待つ | useTranslation.setSuccessDeepLAuthKey | ログで伏せる |
| `/delete/data/deepl_auth_key` | 削除 | `delDeeplAuthKey` | 待つ | useTranslation.deleteSuccessDeepLAuthKey | ログで伏せる |
| `/get/data/selectable_plamo_model_list` | 取得 | `getPlamoModelList` | 待つ | useTranslation.updateFromBackendSelectablePlamoModelList |  |
| `/get/data/selected_plamo_model` | 取得 | `getPlamoModel` | 待つ | useTranslation.updateFromBackendSelectedPlamoModel |  |
| `/set/data/selected_plamo_model` | 設定 | `setPlamoModel` | 待つ | useTranslation.setSuccessSelectedPlamoModel |  |
| `/get/data/plamo_auth_key` | 取得 | `getPlamoAuthKey` | 待つ | useTranslation.updateFromBackendPlamoAuthKey | ログで伏せる |
| `/set/data/plamo_auth_key` | 設定 | `setPlamoAuthKey` | 待つ | useTranslation.setSuccessPlamoAuthKey | ログで伏せる |
| `/delete/data/plamo_auth_key` | 削除 | `delPlamoAuthKey` | 待つ | useTranslation.deleteSuccessPlamoAuthKey | ログで伏せる |
| `/get/data/selectable_gemini_model_list` | 取得 | `getGeminiModelList` | 可 | useTranslation.updateFromBackendSelectableGeminiModelList |  |
| `/get/data/selected_gemini_model` | 取得 | `getGeminiModel` | 可 | useTranslation.updateFromBackendSelectedGeminiModel |  |
| `/set/data/selected_gemini_model` | 設定 | `setGeminiModel` | 可 | useTranslation.setSuccessSelectedGeminiModel |  |
| `/get/data/gemini_auth_key` | 取得 | `getGeminiAuthKey` | 可 | useTranslation.updateFromBackendGeminiAuthKey | ログで伏せる |
| `/set/data/gemini_auth_key` | 設定 | `setGeminiAuthKey` | 可 | useTranslation.setSuccessGeminiAuthKey | ログで伏せる |
| `/delete/data/gemini_auth_key` | 削除 | `delGeminiAuthKey` | 可 | useTranslation.deleteSuccessGeminiAuthKey | ログで伏せる |
| `/get/data/selectable_openai_model_list` | 取得 | `getOpenAIModelList` | 可 | useTranslation.updateFromBackendSelectableOpenAIModelList |  |
| `/get/data/selected_openai_model` | 取得 | `getOpenAIModel` | 可 | useTranslation.updateFromBackendSelectedOpenAIModel |  |
| `/set/data/selected_openai_model` | 設定 | `setOpenAIModel` | 可 | useTranslation.setSuccessSelectedOpenAIModel |  |
| `/get/data/openai_auth_key` | 取得 | `getOpenAIAuthKey` | 可 | useTranslation.updateFromBackendOpenAIAuthKey | ログで伏せる |
| `/set/data/openai_auth_key` | 設定 | `setOpenAIAuthKey` | 可 | useTranslation.setSuccessOpenAIAuthKey | ログで伏せる |
| `/delete/data/openai_auth_key` | 削除 | `delOpenAIAuthKey` | 可 | useTranslation.deleteSuccessOpenAIAuthKey | ログで伏せる |
| `/get/data/selectable_groq_model_list` | 取得 | `getGroqModelList` | 可 | useTranslation.updateFromBackendSelectableGroqModelList |  |
| `/get/data/selected_groq_model` | 取得 | `getGroqModel` | 可 | useTranslation.updateFromBackendSelectedGroqModel |  |
| `/set/data/selected_groq_model` | 設定 | `setGroqModel` | 可 | useTranslation.setSuccessSelectedGroqModel |  |
| `/get/data/groq_auth_key` | 取得 | `getGroqAuthKey` | 可 | useTranslation.updateFromBackendGroqAuthKey | ログで伏せる |
| `/set/data/groq_auth_key` | 設定 | `setGroqAuthKey` | 可 | useTranslation.setSuccessGroqAuthKey | ログで伏せる |
| `/delete/data/groq_auth_key` | 削除 | `delGroqAuthKey` | 可 | useTranslation.deleteSuccessGroqAuthKey | ログで伏せる |
| `/get/data/selectable_openrouter_model_list` | 取得 | `getOpenRouterModelList` | 可 | useTranslation.updateFromBackendSelectableOpenRouterModelList |  |
| `/get/data/selected_openrouter_model` | 取得 | `getOpenRouterModel` | 可 | useTranslation.updateFromBackendSelectedOpenRouterModel |  |
| `/set/data/selected_openrouter_model` | 設定 | `setOpenRouterModel` | 可 | useTranslation.setSuccessSelectedOpenRouterModel |  |
| `/get/data/openrouter_auth_key` | 取得 | `getOpenRouterAuthKey` | 可 | useTranslation.updateFromBackendOpenRouterAuthKey | ログで伏せる |
| `/set/data/openrouter_auth_key` | 設定 | `setOpenRouterAuthKey` | 可 | useTranslation.setSuccessOpenRouterAuthKey | ログで伏せる |
| `/delete/data/openrouter_auth_key` | 削除 | `delOpenRouterAuthKey` | 可 | useTranslation.deleteSuccessOpenRouterAuthKey | ログで伏せる |
| `/get/data/connected_lmstudio` | 取得 | `getTranslatorLMStudioConnection` | 可 | useLLMConnection.setConnectionStatus_LMStudio |  |
| `/run/lmstudio_connection` | 実行 | `checkTranslatorLMStudioConnection` | 可 | useLLMConnection.setConnectionStatus_LMStudio |  |
| `/get/data/selectable_lmstudio_model_list` | 取得 | `getTranslatorLMStudioModelList` | 可 | useTranslation.updateFromBackendSelectableLMStudioModelList |  |
| `/get/data/selected_lmstudio_model` | 取得 | `getTranslatorLMStudioModel` | 可 | useTranslation.updateFromBackendSelectedLMStudioModel |  |
| `/set/data/selected_lmstudio_model` | 設定 | `setTranslatorLMStudioModel` | 可 | useTranslation.setSuccessSelectedLMStudioModel |  |
| `/get/data/lmstudio_url` | 取得 | `getTranslatorLMStudioURL` | 可 | useTranslation.updateFromBackendLMStudioURL |  |
| `/set/data/lmstudio_url` | 設定 | `setTranslatorLMStudioURL` | 可 | useTranslation.setSuccessLMStudioURL |  |
| `/get/data/openai_compatible_auth_key` | 取得 | `getOpenAICompatibleAuthKey` | 可 | useTranslation.updateFromBackendOpenAICompatibleAuthKey | ログで伏せる |
| `/set/data/openai_compatible_auth_key` | 設定 | `setOpenAICompatibleAuthKey` | 可 | useTranslation.setSuccessOpenAICompatibleAuthKey | ログで伏せる |
| `/delete/data/openai_compatible_auth_key` | 削除 | `delOpenAICompatibleAuthKey` | 可 | useTranslation.deleteSuccessOpenAICompatibleAuthKey | ログで伏せる |
| `/get/data/openai_compatible_url` | 取得 | `getOpenAICompatibleURL` | 可 | useTranslation.updateFromBackendOpenAICompatibleURL |  |
| `/set/data/openai_compatible_url` | 設定 | `setOpenAICompatibleURL` | 可 | useTranslation.setSuccessOpenAICompatibleURL |  |
| `/get/data/selectable_openai_compatible_model_list` | 取得 | `getOpenAICompatibleModelList` | 可 | useTranslation.updateFromBackendSelectableOpenAICompatibleModelList |  |
| `/get/data/selected_openai_compatible_model` | 取得 | `getOpenAICompatibleModel` | 可 | useTranslation.updateFromBackendSelectedOpenAICompatibleModel |  |
| `/set/data/selected_openai_compatible_model` | 設定 | `setOpenAICompatibleModel` | 可 | useTranslation.setSuccessSelectedOpenAICompatibleModel |  |
| `/get/data/connected_ollama` | 取得 | `getTranslatorOllamaConnection` | 可 | useLLMConnection.setConnectionStatus_Ollama |  |
| `/run/ollama_connection` | 実行 | `checkTranslatorOllamaConnection` | 可 | useLLMConnection.setConnectionStatus_Ollama |  |
| `/get/data/selectable_ollama_model_list` | 取得 | `getTranslatorOllamaModelList` | 可 | useTranslation.updateFromBackendSelectableOllamaModelList |  |
| `/get/data/selected_ollama_model` | 取得 | `getTranslatorOllamaModel` | 可 | useTranslation.updateFromBackendSelectedOllamaModel |  |
| `/set/data/selected_ollama_model` | 設定 | `setTranslatorOllamaModel` | 可 | useTranslation.setSuccessSelectedOllamaModel |  |
| `/get/data/convert_message_to_romaji` | 取得 | `getConvertMessageToRomaji` | 可 | useOthers.updateFromBackendConvertMessageToRomaji |  |
| `/set/enable/convert_message_to_romaji` | 有効化 | `setEnableConvertMessageToRomaji` | 可 | useOthers.setSuccessConvertMessageToRomaji |  |
| `/set/disable/convert_message_to_romaji` | 無効化 | `setDisableConvertMessageToRomaji` | 可 | useOthers.setSuccessConvertMessageToRomaji |  |
| `/get/data/convert_message_to_hiragana` | 取得 | `getConvertMessageToHiragana` | 可 | useOthers.updateFromBackendConvertMessageToHiragana |  |
| `/set/enable/convert_message_to_hiragana` | 有効化 | `setEnableConvertMessageToHiragana` | 可 | useOthers.setSuccessConvertMessageToHiragana |  |
| `/set/disable/convert_message_to_hiragana` | 無効化 | `setDisableConvertMessageToHiragana` | 可 | useOthers.setSuccessConvertMessageToHiragana |  |
| `/get/data/selectable_mic_host_list` | 取得 | `getMicHostList` | 可 | useDevice.updateFromBackendMicHostList |  |
| `/get/data/selectable_mic_device_list` | 取得 | `getMicDeviceList` | 可 | useDevice.updateFromBackendMicDeviceList |  |
| `/get/data/selectable_speaker_device_list` | 取得 | `getSpeakerDeviceList` | 可 | useDevice.updateFromBackendSpeakerDeviceList |  |
| `/get/data/auto_mic_select` | 取得 | `getAutoMicSelect` | 可 | useDevice.updateFromBackendEnableAutoMicSelect |  |
| `/set/enable/auto_mic_select` | 有効化 | `setEnableAutoMicSelect` | 可 | useDevice.setSuccessEnableAutoMicSelect |  |
| `/set/disable/auto_mic_select` | 無効化 | `setDisableAutoMicSelect` | 可 | useDevice.setSuccessEnableAutoMicSelect |  |
| `/get/data/selected_mic_host` | 取得 | `getSelectedMicHost` | 可 | useDevice.updateFromBackendSelectedMicHost |  |
| `/set/data/selected_mic_host` | 設定 | `setSelectedMicHost` | 可 | useDevice.setSuccessSelectedMicHost |  |
| `/get/data/selected_mic_device` | 取得 | `getSelectedMicDevice` | 可 | useDevice.updateFromBackendSelectedMicDevice |  |
| `/set/data/selected_mic_device` | 設定 | `setSelectedMicDevice` | 可 | useDevice.setSuccessSelectedMicDevice |  |
| `/get/data/mic_threshold` | 取得 | `getMicThreshold` | 可 | useDevice.updateFromBackendMicThreshold |  |
| `/set/data/mic_threshold` | 設定 | `setMicThreshold` | 可 | useDevice.setSuccessMicThreshold |  |
| `/get/data/mic_automatic_threshold` | 取得 | `getMicAutomaticThreshold` | 可 | useDevice.updateFromBackendEnableAutomaticMicThreshold |  |
| `/set/enable/mic_automatic_threshold` | 有効化 | `setEnableMicAutomaticThreshold` | 可 | useDevice.setSuccessEnableAutomaticMicThreshold |  |
| `/set/disable/mic_automatic_threshold` | 無効化 | `setDisableMicAutomaticThreshold` | 可 | useDevice.setSuccessEnableAutomaticMicThreshold |  |
| `/get/data/mic_record_timeout` | 取得 | `getMicRecordTimeout` | 可 | useTranscription.updateFromBackendMicRecordTimeout |  |
| `/set/data/mic_record_timeout` | 設定 | `setMicRecordTimeout` | 可 | useTranscription.setSuccessMicRecordTimeout |  |
| `/get/data/mic_phrase_timeout` | 取得 | `getMicPhraseTimeout` | 可 | useTranscription.updateFromBackendMicPhraseTimeout |  |
| `/set/data/mic_phrase_timeout` | 設定 | `setMicPhraseTimeout` | 可 | useTranscription.setSuccessMicPhraseTimeout |  |
| `/get/data/mic_max_phrases` | 取得 | `getMicMaxPhrases` | 可 | useTranscription.updateFromBackendMicMaxWords |  |
| `/set/data/mic_max_phrases` | 設定 | `setMicMaxPhrases` | 可 | useTranscription.setSuccessMicMaxWords |  |
| `/get/data/hotkeys` | 取得 | `getHotkeys` | 可 | useHotkeys.updateHotkeys |  |
| `/set/data/hotkeys` | 設定 | `setHotkeys` | 可 | useHotkeys.setSuccessHotkeys |  |
| `/get/data/mic_avg_logprob` | 取得 | `getMicAvgLogprob` | 可 | useTranscription.updateFromBackendMicAvgLogprob |  |
| `/set/data/mic_avg_logprob` | 設定 | `setMicAvgLogprob` | 可 | useTranscription.setSuccessMicAvgLogprob |  |
| `/get/data/mic_no_speech_prob` | 取得 | `getMicNoSpeechProb` | 可 | useTranscription.updateFromBackendMicNoSpeechProb |  |
| `/set/data/mic_no_speech_prob` | 設定 | `setMicNoSpeechProb` | 可 | useTranscription.setSuccessMicNoSpeechProb |  |
| `/get/data/mic_vad_filter` | 取得 | `getMicVadFilter` | 可 | useDevice.updateFromBackendMicVadFilter |  |
| `/set/enable/mic_vad_filter` | 有効化 | `setEnableMicVadFilter` | 可 | useDevice.setSuccessMicVadFilter |  |
| `/set/disable/mic_vad_filter` | 無効化 | `setDisableMicVadFilter` | 可 | useDevice.setSuccessMicVadFilter |  |
| `/set/enable/check_mic_threshold` | 有効化 | `setEnableCheckMicThreshold` | 可 | useVolume.updateMicThresholdCheckStatus |  |
| `/set/disable/check_mic_threshold` | 無効化 | `setDisableCheckMicThreshold` | 可 | useVolume.updateMicThresholdCheckStatus |  |
| `/get/data/mic_word_filter` | 取得 | `getMicWordFilter` | 可 | useTranscription.updateFromBackendMicWordFilterList |  |
| `/set/data/mic_word_filter` | 設定 | `setMicWordFilter` | 可 | useTranscription.setSuccessMicWordFilterList |  |
| `/get/data/auto_speaker_select` | 取得 | `getAutoSpeakerSelect` | 可 | useDevice.updateFromBackendEnableAutoSpeakerSelect |  |
| `/set/enable/auto_speaker_select` | 有効化 | `setEnableAutoSpeakerSelect` | 可 | useDevice.setSuccessEnableAutoSpeakerSelect |  |
| `/set/disable/auto_speaker_select` | 無効化 | `setDisableAutoSpeakerSelect` | 可 | useDevice.setSuccessEnableAutoSpeakerSelect |  |
| `/get/data/selected_speaker_device` | 取得 | `getSelectedSpeakerDevice` | 可 | useDevice.updateFromBackendSelectedSpeakerDevice |  |
| `/set/data/selected_speaker_device` | 設定 | `setSelectedSpeakerDevice` | 可 | useDevice.setSuccessSelectedSpeakerDevice |  |
| `/get/data/speaker_threshold` | 取得 | `getSpeakerThreshold` | 可 | useDevice.updateFromBackendSpeakerThreshold |  |
| `/set/data/speaker_threshold` | 設定 | `setSpeakerThreshold` | 可 | useDevice.setSuccessSpeakerThreshold |  |
| `/get/data/speaker_automatic_threshold` | 取得 | `getSpeakerAutomaticThreshold` | 可 | useDevice.updateFromBackendEnableAutomaticSpeakerThreshold |  |
| `/set/enable/speaker_automatic_threshold` | 有効化 | `setEnableSpeakerAutomaticThreshold` | 可 | useDevice.setSuccessEnableAutomaticSpeakerThreshold |  |
| `/set/disable/speaker_automatic_threshold` | 無効化 | `setDisableSpeakerAutomaticThreshold` | 可 | useDevice.setSuccessEnableAutomaticSpeakerThreshold |  |
| `/get/data/speaker_record_timeout` | 取得 | `getSpeakerRecordTimeout` | 可 | useTranscription.updateFromBackendSpeakerRecordTimeout |  |
| `/set/data/speaker_record_timeout` | 設定 | `setSpeakerRecordTimeout` | 可 | useTranscription.setSuccessSpeakerRecordTimeout |  |
| `/get/data/speaker_phrase_timeout` | 取得 | `getSpeakerPhraseTimeout` | 可 | useTranscription.updateFromBackendSpeakerPhraseTimeout |  |
| `/set/data/speaker_phrase_timeout` | 設定 | `setSpeakerPhraseTimeout` | 可 | useTranscription.setSuccessSpeakerPhraseTimeout |  |
| `/get/data/speaker_max_phrases` | 取得 | `getSpeakerMaxPhrases` | 可 | useTranscription.updateFromBackendSpeakerMaxWords |  |
| `/set/data/speaker_max_phrases` | 設定 | `setSpeakerMaxPhrases` | 可 | useTranscription.setSuccessSpeakerMaxWords |  |
| `/get/data/speaker_avg_logprob` | 取得 | `getSpeakerAvgLogprob` | 可 | useTranscription.updateFromBackendSpeakerAvgLogprob |  |
| `/set/data/speaker_avg_logprob` | 設定 | `setSpeakerAvgLogprob` | 可 | useTranscription.setSuccessSpeakerAvgLogprob |  |
| `/get/data/speaker_no_speech_prob` | 取得 | `getSpeakerNoSpeechProb` | 可 | useTranscription.updateFromBackendSpeakerNoSpeechProb |  |
| `/set/data/speaker_no_speech_prob` | 設定 | `setSpeakerNoSpeechProb` | 可 | useTranscription.setSuccessSpeakerNoSpeechProb |  |
| `/get/data/speaker_vad_filter` | 取得 | `getSpeakerVadFilter` | 可 | useDevice.updateFromBackendSpeakerVadFilter |  |
| `/set/enable/speaker_vad_filter` | 有効化 | `setEnableSpeakerVadFilter` | 可 | useDevice.setSuccessSpeakerVadFilter |  |
| `/set/disable/speaker_vad_filter` | 無効化 | `setDisableSpeakerVadFilter` | 可 | useDevice.setSuccessSpeakerVadFilter |  |
| `/set/enable/check_speaker_threshold` | 有効化 | `setEnableCheckSpeakerThreshold` | 可 | useVolume.updateSpeakerThresholdCheckStatus |  |
| `/set/disable/check_speaker_threshold` | 無効化 | `setDisableCheckSpeakerThreshold` | 可 | useVolume.updateSpeakerThresholdCheckStatus |  |
| `/get/data/selectable_whisper_weight_type_dict` | 取得 | `getSelectableWhisperWeightTypeDict` | 可 | useTranscription.updateDownloadedWhisperWeightTypeStatus |  |
| `/get/data/selected_whisper_weight_type` | 取得 | `getWhisperWeightType` | 可 | useTranscription.updateFromBackendSelectedWhisperWeightType |  |
| `/set/data/selected_whisper_weight_type` | 設定 | `setWhisperWeightType` | 可 | useTranscription.setSuccessSelectedWhisperWeightType |  |
| `/get/data/selected_transcription_compute_type` | 取得 | `getSelectedTranscriptionComputeType` | 可 | useTranscription.updateFromBackendSelectedTranscriptionComputeType |  |
| `/set/data/selected_transcription_compute_type` | 設定 | `setSelectedTranscriptionComputeType` | 可 | useTranscription.setSuccessSelectedTranscriptionComputeType |  |
| `/run/download_whisper_weight` | 実行 | `downloadWhisperWeight` | 可 | useTranscription.downloadedWhisperWeightTypeStatus |  |
| `/get/data/overlay_small_log` | 取得 | `getOverlaySmallLog` | 可 | useVr.updateFromBackendIsEnabledOverlaySmallLog |  |
| `/set/enable/overlay_small_log` | 有効化 | `setEnableOverlaySmallLog` | 可 | useVr.setSuccessIsEnabledOverlaySmallLog |  |
| `/set/disable/overlay_small_log` | 無効化 | `setDisableOverlaySmallLog` | 可 | useVr.setSuccessIsEnabledOverlaySmallLog |  |
| `/get/data/overlay_small_log_settings` | 取得 | `getOverlaySmallLogSettings` | 可 | useVr.updateFromBackendOverlaySmallLogSettings |  |
| `/run/vr_panel_tooltip` | 実行 | `setVrPanelTooltip` | 待つ | （受け取るだけ） |  |
| `/run/vr_panel_windows` | 実行 | `setVrPanelWindows` | 待つ | （受け取るだけ） |  |
| `/run/vr_panel_recall_log` | 実行 | `recallVrPanelLog` | 待つ | （受け取るだけ） |  |
| `/run/vr_launcher_reset` | 実行 | `resetVrLauncher` | 待つ | （受け取るだけ） |  |
| `/get/data/overlay_vr_panel_opacity` | 取得 | `getOverlayVrPanelOpacity` | 可 | useVr.updateFromBackendOverlayVrPanelOpacity |  |
| `/get/data/overlay_vr_panel_anchor` | 取得 | `getOverlayVrPanelAnchor` | 可 | useVr.updateFromBackendOverlayVrPanelAnchor |  |
| `/get/data/vr_panel_layout` | 取得 | `getVrPanelLayout` | 可 | useVr.updateFromBackendVrPanelLayout |  |
| `/run/vr_panel_layout_rendered` | 実行 | `setVrPanelLayoutRendered` | 可 | （受け取るだけ） |  |
| `/set/data/overlay_vr_panel_anchor` | 設定 | `setOverlayVrPanelAnchor` | 可 | useVr.setSuccessOverlayVrPanelAnchor |  |
| `/get/data/overlay_vr_panel_locked` | 取得 | `getOverlayVrPanelLocked` | 可 | useVr.updateFromBackendOverlayVrPanelLocked |  |
| `/get/data/overlay_vr_panel_font_size` | 取得 | `getOverlayVrPanelFontSize` | 可 | useVr.updateFromBackendOverlayVrPanelFontSize |  |
| `/get/data/overlay_vr_launcher_hand` | 取得 | `getOverlayVrLauncherHand` | 可 | useVr.updateFromBackendOverlayVrLauncherHand |  |
| `/set/data/overlay_vr_launcher_hand` | 設定 | `setOverlayVrLauncherHand` | 可 | useVr.setSuccessOverlayVrLauncherHand |  |
| `/get/data/overlay_vr_launcher_auto_hide` | 取得 | `getOverlayVrLauncherAutoHide` | 可 | useVr.updateFromBackendOverlayVrLauncherAutoHide |  |
| `/set/enable/overlay_vr_launcher_auto_hide` | 有効化 | `setEnableOverlayVrLauncherAutoHide` | 可 | useVr.setSuccessOverlayVrLauncherAutoHide |  |
| `/set/disable/overlay_vr_launcher_auto_hide` | 無効化 | `setDisableOverlayVrLauncherAutoHide` | 可 | useVr.setSuccessOverlayVrLauncherAutoHide |  |
| `/get/data/overlay_vr_tooltip` | 取得 | `getOverlayVrTooltip` | 可 | useVr.updateFromBackendOverlayVrTooltip |  |
| `/set/enable/overlay_vr_tooltip` | 有効化 | `setEnableOverlayVrTooltip` | 可 | useVr.setSuccessOverlayVrTooltip |  |
| `/set/disable/overlay_vr_tooltip` | 無効化 | `setDisableOverlayVrTooltip` | 可 | useVr.setSuccessOverlayVrTooltip |  |
| `/set/data/overlay_vr_panel_font_size` | 設定 | `setOverlayVrPanelFontSize` | 可 | useVr.setSuccessOverlayVrPanelFontSize |  |
| `/set/enable/overlay_vr_panel_locked` | 有効化 | `setEnableOverlayVrPanelLocked` | 可 | useVr.setSuccessOverlayVrPanelLocked |  |
| `/set/disable/overlay_vr_panel_locked` | 無効化 | `setDisableOverlayVrPanelLocked` | 可 | useVr.setSuccessOverlayVrPanelLocked |  |
| `/set/data/overlay_vr_panel_opacity` | 設定 | `setOverlayVrPanelOpacity` | 可 | useVr.setSuccessOverlayVrPanelOpacity |  |
| `/set/data/overlay_small_log_settings` | 設定 | `setOverlaySmallLogSettings` | 可 | useVr.setSuccessOverlaySmallLogSettings |  |
| `/get/data/overlay_large_log` | 取得 | `getOverlayLargeLog` | 可 | useVr.updateFromBackendIsEnabledOverlayLargeLog |  |
| `/get/data/overlay_vr_panel` | 取得 | `getOverlayVrPanel` | 可 | useVr.updateFromBackendIsEnabledOverlayVrPanel |  |
| `/set/enable/overlay_vr_panel` | 有効化 | `setEnableOverlayVrPanel` | 可 | useVr.setSuccessIsEnabledOverlayVrPanel |  |
| `/set/disable/overlay_vr_panel` | 無効化 | `setDisableOverlayVrPanel` | 可 | useVr.setSuccessIsEnabledOverlayVrPanel |  |
| `/set/enable/overlay_large_log` | 有効化 | `setEnableOverlayLargeLog` | 可 | useVr.setSuccessIsEnabledOverlayLargeLog |  |
| `/set/disable/overlay_large_log` | 無効化 | `setDisableOverlayLargeLog` | 可 | useVr.setSuccessIsEnabledOverlayLargeLog |  |
| `/get/data/overlay_large_log_settings` | 取得 | `getOverlayLargeLogSettings` | 可 | useVr.updateFromBackendOverlayLargeLogSettings |  |
| `/set/data/overlay_large_log_settings` | 設定 | `setOverlayLargeLogSettings` | 可 | useVr.setSuccessOverlayLargeLogSettings |  |
| `/get/data/overlay_show_only_translated_messages` | 取得 | `getOverlayShowOnlyTranslatedMessages` | 可 | useVr.updateFromBackendOverlayShowOnlyTranslatedMessages |  |
| `/set/enable/overlay_show_only_translated_messages` | 有効化 | `setEnableOverlayShowOnlyTranslatedMessages` | 可 | useVr.setSuccessOverlayShowOnlyTranslatedMessages |  |
| `/set/disable/overlay_show_only_translated_messages` | 無効化 | `setDisableOverlayShowOnlyTranslatedMessages` | 可 | useVr.setSuccessOverlayShowOnlyTranslatedMessages |  |
| `/get/data/send_message_format_parts` | 取得 | `getSendMessageFormatParts` | 可 | useOthers.updateFromBackendSendMessageFormatParts |  |
| `/set/data/send_message_format_parts` | 設定 | `setSendMessageFormatParts` | 可 | useOthers.setSuccessSendMessageFormatParts |  |
| `/get/data/received_message_format_parts` | 取得 | `getReceivedMessageFormatParts` | 可 | useOthers.updateFromBackendReceivedMessageFormatParts |  |
| `/set/data/received_message_format_parts` | 設定 | `setReceivedMessageFormatParts` | 可 | useOthers.setSuccessReceivedMessageFormatParts |  |
| `/get/data/auto_clear_message_box` | 取得 | `getAutoClearMessageBox` | 可 | useOthers.updateFromBackendEnableAutoClearMessageInputBox |  |
| `/set/enable/auto_clear_message_box` | 有効化 | `setEnableAutoClearMessageBox` | 可 | useOthers.setSuccessEnableAutoClearMessageInputBox |  |
| `/set/disable/auto_clear_message_box` | 無効化 | `setDisableAutoClearMessageBox` | 可 | useOthers.setSuccessEnableAutoClearMessageInputBox |  |
| `/get/data/send_only_translated_messages` | 取得 | `getSendOnlyTranslatedMessages` | 可 | useOthers.updateFromBackendEnableSendOnlyTranslatedMessages |  |
| `/set/enable/send_only_translated_messages` | 有効化 | `setEnableSendOnlyTranslatedMessages` | 可 | useOthers.setSuccessEnableSendOnlyTranslatedMessages |  |
| `/set/disable/send_only_translated_messages` | 無効化 | `setDisableSendOnlyTranslatedMessages` | 可 | useOthers.setSuccessEnableSendOnlyTranslatedMessages |  |
| `/get/data/logger_feature` | 取得 | `getLoggerFeature` | 可 | useOthers.updateFromBackendEnableAutoExportMessageLogs |  |
| `/set/enable/logger_feature` | 有効化 | `setEnableLoggerFeature` | 可 | useOthers.setSuccessEnableAutoExportMessageLogs |  |
| `/set/disable/logger_feature` | 無効化 | `setDisableLoggerFeature` | 可 | useOthers.setSuccessEnableAutoExportMessageLogs |  |
| `/run/open_filepath_logs` | 実行 | `openFilepathLogs` | 可 | useOpenFolder.openedFolder_MessageLogs |  |
| `/get/data/vrc_mic_mute_sync` | 取得 | `getVrcMicMuteSync` | 可 | useOthers.updateFromBackendEnableVrcMicMuteSync |  |
| `/set/enable/vrc_mic_mute_sync` | 有効化 | `setEnableVrcMicMuteSync` | 可 | useOthers.setSuccessEnableVrcMicMuteSync |  |
| `/set/disable/vrc_mic_mute_sync` | 無効化 | `setDisableVrcMicMuteSync` | 可 | useOthers.setSuccessEnableVrcMicMuteSync |  |
| `/get/data/send_message_to_vrc` | 取得 | `getSendMessageToVrc` | 可 | useOthers.updateFromBackendEnableSendMessageToVrc |  |
| `/set/enable/send_message_to_vrc` | 有効化 | `setEnableSendMessageToVrc` | 可 | useOthers.setSuccessEnableSendMessageToVrc |  |
| `/set/disable/send_message_to_vrc` | 無効化 | `setDisableSendMessageToVrc` | 可 | useOthers.setSuccessEnableSendMessageToVrc |  |
| `/get/data/send_received_message_to_vrc` | 取得 | `getSendReceivedMessageToVrc` | 可 | useOthers.updateFromBackendEnableSendReceivedMessageToVrc |  |
| `/set/enable/send_received_message_to_vrc` | 有効化 | `setEnableSendReceivedMessageToVrc` | 可 | useOthers.setSuccessEnableSendReceivedMessageToVrc |  |
| `/set/disable/send_received_message_to_vrc` | 無効化 | `setDisableSendReceivedMessageToVrc` | 可 | useOthers.setSuccessEnableSendReceivedMessageToVrc |  |
| `/get/data/model_download_catalog` | 取得 | `getModelDownloadCatalog` | 可 | useModelDownloads.updateCatalog |  |
| `/get/data/model_download_hardware` | 取得 | `getModelDownloadHardware` | 可 | useModelDownloads.updateHardware |  |
| `/run/refresh_model_download_hardware` | 実行 | `refreshModelDownloadHardware` | 可 | useModelDownloads.updateHardware |  |
| `/get/data/model_download_state` | 取得 | `getModelDownloadState` | 可 | useModelDownloads.updateState |  |
| `/run/start_model_download` | 実行 | `startModelDownload` | 可 | useModelDownloads.acknowledge |  |
| `/run/cancel_model_download` | 実行 | `cancelModelDownload` | 可 | useModelDownloads.acknowledge |  |
| `/run/apply_model_download` | 実行 | `applyModelDownload` | 可 | useModelDownloads.acknowledge |  |
| `/get/data/speech_server_settings` | 取得 | `getSpeechServerSettings` | 可 | useSpeechServers.updateSettings |  |
| `/set/data/speech_server_settings` | 設定 | `setSpeechServerSettings` | 可 | useSpeechServers.updateSettings |  |
| `/get/data/speech_server_state` | 取得 | `getSpeechServerState` | 可 | useSpeechServers.updateState |  |
| `/run/start_speech_server` | 実行 | `startSpeechServer` | 可 | useSpeechServers.updateState |  |
| `/run/stop_speech_server` | 実行 | `stopSpeechServer` | 可 | useSpeechServers.updateState | 即時（キューを通らない） |
| `/get/data/realtime_asr_settings` | 取得 | `getRealtimeASRSettings` | 可 | useRealtimeASR.updateSettings |  |
| `/set/data/realtime_asr_settings` | 設定 | `setRealtimeASRSettings` | 可 | useRealtimeASR.updateSettings |  |
| `/get/data/realtime_asr_endpoints` | 取得 | `getRealtimeASREndpoints` | 可 | useRealtimeASR.updateEndpoints |  |
| `/get/data/realtime_asr_models` | 取得 | `getRealtimeASRModels` | 可 | useRealtimeASR.updateModels |  |
| `/get/data/realtime_asr_state` | 取得 | `getRealtimeASRState` | 可 | useRealtimeASR.updateState |  |
| `/run/start_realtime_asr` | 実行 | `startRealtimeASR` | 可 | useRealtimeASR.updateState |  |
| `/run/stop_realtime_asr` | 実行 | `stopRealtimeASR` | 可 | useRealtimeASR.updateState | 即時（キューを通らない） |
| `/get/data/voice_settings` | 取得 | `getVoiceSettings` | 可 | useVoice.updateSettings | ログで伏せる |
| `/set/data/voice_settings` | 設定 | `setVoiceSettings` | 可 | useVoice.updateSettings | ログで伏せる |
| `/get/data/voice_status` | 取得 | `getVoiceStatus` | 可 | useVoice.updateStatus |  |
| `/get/data/tts_model_options` | 取得 | `getTtsModelOptions` | 可 | useVoice.updateModelOptions |  |
| `/get/data/voice_output_devices` | 取得 | `getVoiceOutputDevices` | 可 | useVoice.updateDevices |  |
| `/run/stop_voice` | 実行 | `stopVoice` | 可 | useVoice.updateStatus | 即時（キューを通らない） |
| `/run/enable_tts` | 実行 | `enableTts` | 可 | useVoice.updateStatus |  |
| `/run/disable_tts` | 実行 | `disableTts` | 可 | useVoice.updateStatus | 即時（キューを通らない） |
| `/get/data/voice_route` | 取得 | `getVoiceRoute` | 可 | useVoice.updateRoute |  |
| `/run/mute_voice` | 実行 | `muteVoice` | 可 | useVoice.updateRoute | 即時（キューを通らない） |
| `/run/resume_voice` | 実行 | `resumeVoice` | 可 | useVoice.updateRoute | 即時（キューを通らない） |
| `/get/data/direct_voice_sources` | 取得 | `getDirectVoiceSources` | 可 | useVoice.updateDirectSources |  |
| `/set/data/direct_voice_settings` | 設定 | `setDirectVoiceSettings` | 可 | useVoice.updateDirectState | ログで伏せる |
| `/get/data/direct_voice_state` | 取得 | `getDirectVoiceState` | 可 | useVoice.updateDirectState |  |
| `/run/start_direct_voice` | 実行 | `startDirectVoice` | 可 | useVoice.updateDirectState |  |
| `/run/stop_direct_voice` | 実行 | `stopDirectVoice` | 可 | useVoice.updateDirectState | 即時（キューを通らない） |
| `/get/data/websocket_host` | 取得 | `getWebSocketHost` | 可 | useAdvancedSettings.updateFromBackendWebsocketHost |  |
| `/set/data/websocket_host` | 設定 | `setWebSocketHost` | 可 | useAdvancedSettings.setSuccessWebsocketHost |  |
| `/get/data/websocket_port` | 取得 | `getWebSocketPort` | 可 | useAdvancedSettings.updateFromBackendWebsocketPort |  |
| `/set/data/websocket_port` | 設定 | `setWebSocketPort` | 可 | useAdvancedSettings.setSuccessWebsocketPort |  |
| `/get/data/websocket_auth_token` | 取得 | `getWebSocketAuthToken` | 可 | useAdvancedSettings.updateFromBackendWebsocketAuthToken | ログで伏せる |
| `/get/data/websocket_server` | 取得 | `getWebSocketServer` | 可 | useAdvancedSettings.updateFromBackendEnableWebsocket |  |
| `/set/enable/websocket_server` | 有効化 | `setEnableWebSocketServer` | 可 | useAdvancedSettings.setSuccessEnableWebsocket |  |
| `/set/disable/websocket_server` | 無効化 | `setDisableWebSocketServer` | 可 | useAdvancedSettings.setSuccessEnableWebsocket |  |
| `/get/data/obs_browser_source` | 取得 | `getObsBrowserSource` | 可 | useAdvancedSettings.updateFromBackendEnableObsBrowserSource |  |
| `/set/enable/obs_browser_source` | 有効化 | `setEnableObsBrowserSource` | 可 | useAdvancedSettings.setSuccessEnableObsBrowserSource |  |
| `/set/disable/obs_browser_source` | 無効化 | `setDisableObsBrowserSource` | 可 | useAdvancedSettings.setSuccessEnableObsBrowserSource |  |
| `/get/data/obs_browser_source_port` | 取得 | `getObsBrowserSourcePort` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourcePort |  |
| `/set/data/obs_browser_source_port` | 設定 | `setObsBrowserSourcePort` | 可 | useAdvancedSettings.setSuccessObsBrowserSourcePort |  |
| `/get/data/obs_browser_source_max_messages` | 取得 | `getObsBrowserSourceMaxMessages` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceMaxMessages |  |
| `/set/data/obs_browser_source_max_messages` | 設定 | `setObsBrowserSourceMaxMessages` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceMaxMessages |  |
| `/get/data/obs_browser_source_display_duration` | 取得 | `getObsBrowserSourceDisplayDuration` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceDisplayDuration |  |
| `/set/data/obs_browser_source_display_duration` | 設定 | `setObsBrowserSourceDisplayDuration` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceDisplayDuration |  |
| `/get/data/obs_browser_source_fadeout_duration` | 取得 | `getObsBrowserSourceFadeoutDuration` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceFadeoutDuration |  |
| `/set/data/obs_browser_source_fadeout_duration` | 設定 | `setObsBrowserSourceFadeoutDuration` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceFadeoutDuration |  |
| `/get/data/obs_browser_source_font_size` | 取得 | `getObsBrowserSourceFontSize` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceFontSize |  |
| `/set/data/obs_browser_source_font_size` | 設定 | `setObsBrowserSourceFontSize` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceFontSize |  |
| `/get/data/obs_browser_source_font_color` | 取得 | `getObsBrowserSourceFontColor` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceFontColor |  |
| `/set/data/obs_browser_source_font_color` | 設定 | `setObsBrowserSourceFontColor` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceFontColor |  |
| `/get/data/obs_browser_source_font_outline_thickness` | 取得 | `getObsBrowserSourceFontOutlineThickness` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceFontOutlineThickness |  |
| `/set/data/obs_browser_source_font_outline_thickness` | 設定 | `setObsBrowserSourceFontOutlineThickness` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceFontOutlineThickness |  |
| `/get/data/obs_browser_source_font_outline_color` | 取得 | `getObsBrowserSourceFontOutlineColor` | 可 | useAdvancedSettings.updateFromBackendObsBrowserSourceFontOutlineColor |  |
| `/set/data/obs_browser_source_font_outline_color` | 設定 | `setObsBrowserSourceFontOutlineColor` | 可 | useAdvancedSettings.setSuccessObsBrowserSourceFontOutlineColor |  |
| `/get/data/clipboard` | 取得 | `getClipboard` | 可 | useVr.updateFromBackendVoiceTypingMode |  |
| `/set/enable/clipboard` | 有効化 | `setEnableClipboard` | 可 | useVr.setSuccessVoiceTypingMode |  |
| `/set/disable/clipboard` | 無効化 | `setDisableClipboard` | 可 | useVr.setSuccessVoiceTypingMode |  |
| `/get/data/selectable_ocr_source_languages` | 取得 | `getSelectableOcrSourceLanguages` | 可 | useOcr.updateFromBackendSelectableOcrSourceLanguageList |  |
| `/get/data/ocr_source_language` | 取得 | `getOcrSourceLanguage` | 可 | useOcr.updateFromBackendOcrSourceLanguage |  |
| `/set/data/ocr_source_language` | 設定 | `setOcrSourceLanguage` | 可 | useOcr.setSuccessOcrSourceLanguage |  |
| `/get/data/ocr_window_title` | 取得 | `getOcrWindowTitle` | 可 | useOcr.updateFromBackendOcrWindowTitle |  |
| `/set/data/ocr_window_title` | 設定 | `setOcrWindowTitle` | 可 | useOcr.setSuccessOcrWindowTitle |  |
| `/get/data/ocr_poll_interval_ms` | 取得 | `getOcrPollIntervalMs` | 可 | useOcr.updateFromBackendOcrPollIntervalMs |  |
| `/set/data/ocr_poll_interval_ms` | 設定 | `setOcrPollIntervalMs` | 可 | useOcr.setSuccessOcrPollIntervalMs |  |
| `/get/data/ocr_min_confidence` | 取得 | `getOcrMinConfidence` | 可 | useOcr.updateFromBackendOcrMinConfidence |  |
| `/set/data/ocr_min_confidence` | 設定 | `setOcrMinConfidence` | 可 | useOcr.setSuccessOcrMinConfidence |  |
| `/get/data/ocr_bubble_min_text_length` | 取得 | `getOcrBubbleMinTextLength` | 可 | useOcr.updateFromBackendOcrBubbleMinTextLength |  |
| `/set/data/ocr_bubble_min_text_length` | 設定 | `setOcrBubbleMinTextLength` | 可 | useOcr.setSuccessOcrBubbleMinTextLength |  |
| `/get/data/ocr_capture_region` | 取得 | `getOcrCaptureRegion` | 可 | useOcr.updateFromBackendOcrCaptureRegion |  |
| `/set/data/ocr_capture_region` | 設定 | `setOcrCaptureRegion` | 可 | useOcr.setSuccessOcrCaptureRegion |  |
| `/get/data/ocr_chatbox_filter` | 取得 | `getOcrChatboxFilter` | 可 | useOcr.updateFromBackendOcrChatboxFilter |  |
| `/set/enable/ocr_chatbox_filter` | 有効化 | `setEnableOcrChatboxFilter` | 可 | useOcr.setSuccessOcrChatboxFilter |  |
| `/set/disable/ocr_chatbox_filter` | 無効化 | `setDisableOcrChatboxFilter` | 可 | useOcr.setSuccessOcrChatboxFilter |  |
| `/get/data/ocr_use_chatbox_detector` | 取得 | `getOcrUseChatboxDetector` | 可 | useOcr.updateFromBackendOcrUseChatboxDetector |  |
| `/set/enable/ocr_use_chatbox_detector` | 有効化 | `setEnableOcrUseChatboxDetector` | 可 | useOcr.setSuccessOcrUseChatboxDetector |  |
| `/set/disable/ocr_use_chatbox_detector` | 無効化 | `setDisableOcrUseChatboxDetector` | 可 | useOcr.setSuccessOcrUseChatboxDetector |  |
| `/get/data/ocr_readiness` | 取得 | `getOcrReadiness` | 可 | useOcr.updateFromBackendOcrReadiness |  |
| `/get/data/osc_ip_address` | 取得 | `getOscIpAddress` | 可 | useAdvancedSettings.updateFromBackendOscIpAddress |  |
| `/set/data/osc_ip_address` | 設定 | `setOscIpAddress` | 可 | useAdvancedSettings.setSuccessOscIpAddress |  |
| `/get/data/osc_port` | 取得 | `getOscPort` | 可 | useAdvancedSettings.updateFromBackendOscPort |  |
| `/set/data/osc_port` | 設定 | `setOscPort` | 可 | useAdvancedSettings.setSuccessOscPort |  |
| `/get/data/notification_vrc_sfx` | 取得 | `getNotificationVrcSfx` | 可 | useOthers.updateFromBackendEnableNotificationVrcSfx |  |
| `/set/enable/notification_vrc_sfx` | 有効化 | `setEnableNotificationVrcSfx` | 可 | useOthers.setSuccessEnableNotificationVrcSfx |  |
| `/set/disable/notification_vrc_sfx` | 無効化 | `setDisableNotificationVrcSfx` | 可 | useOthers.setSuccessEnableNotificationVrcSfx |  |
| `/run/open_filepath_config_file` | 実行 | `openFilepathConfigFile` | 可 | useOpenFolder.openedFolder_ConfigFile |  |
| `/run/feed_watchdog` | 実行 | `feedWatchdog` | 可 | （受け取るだけ） |  |


## 通知（サイドカーからUIへ、87件）

要求への応答とは別に、サイドカーが自分から送るメッセージ。`controller.run(status, run_mapping[名前], result)`で送る。

| 名前 | エンドポイント | UIの受信先 |
|---|---|---|
| `enable_translation` | `/run/enable_translation` | — |
| `enable_transcription_send` | `/run/enable_transcription_send` | — |
| `enable_transcription_receive` | `/run/enable_transcription_receive` | — |
| `disable_transcription_send` | `/set/disable/transcription_send` | useMainFunction.updateTranscriptionSendStatus |
| `disable_transcription_receive` | `/set/disable/transcription_receive` | useMainFunction.updateTranscriptionReceiveStatus |
| `disable_check_mic_threshold` | `/set/disable/check_mic_threshold` | useVolume.updateMicThresholdCheckStatus |
| `disable_check_speaker_threshold` | `/set/disable/check_speaker_threshold` | useVolume.updateSpeakerThresholdCheckStatus |
| `connected_network` | `/run/connected_network` | useHandleNetworkConnection.handleNetworkConnection |
| `enable_ai_models` | `/run/enable_ai_models` | useIsVrctAvailable.handleAiModelsAvailability |
| `update_software` | `/run/update_software` | （受け取るだけ） |
| `update_cuda_software` | `/run/update_cuda_software` | （受け取るだけ） |
| `transcription_mic` | `/run/transcription_send_mic_message` | useMessage.addSentMessageLog |
| `transcription_speaker` | `/run/transcription_receive_speaker_message` | useMessage.addReceivedMessageLog |
| `transcription_ocr` | `/run/transcription_ocr_message` | useMessage.addReceivedMessageLog |
| `enable_ocr_capture` | `/run/enable_ocr_capture` | — |
| `check_mic_volume` | `/run/check_mic_volume` | useVolume.updateVolumeVariable_Mic |
| `check_speaker_volume` | `/run/check_speaker_volume` | useVolume.updateVolumeVariable_Speaker |
| `error_device` | `/run/error_device` | — |
| `error_translation_engine` | `/run/error_translation_engine` | — |
| `error_translation_enable_vram_overflow` | `/run/error_translation_enable_vram_overflow` | — |
| `error_translation_chat_vram_overflow` | `/run/error_translation_chat_vram_overflow` | — |
| `error_translation_mic_vram_overflow` | `/run/error_translation_mic_vram_overflow` | — |
| `error_translation_speaker_vram_overflow` | `/run/error_translation_speaker_vram_overflow` | — |
| `error_transcription_mic_vram_overflow` | `/run/error_transcription_mic_vram_overflow` | — |
| `error_transcription_speaker_vram_overflow` | `/run/error_transcription_speaker_vram_overflow` | — |
| `word_filter` | `/run/word_filter` | useMessage.addSystemMessageLog_FromBackend |
| `transcription_recognition_error` | `/run/transcription_recognition_error` | useMessage.addSystemMessageLog_FromBackend |
| `download_progress_ctranslate2_weight` | `/run/download_progress_ctranslate2_weight` | useTranslation.updateDownloadProgressCTranslate2WeightTypeStatus |
| `downloaded_ctranslate2_weight` | `/run/downloaded_ctranslate2_weight` | useTranslation.downloadedCTranslate2WeightTypeStatus |
| `error_ctranslate2_weight` | `/run/error_ctranslate2_weight` | — |
| `ctranslate2_license_notice` | `/run/ctranslate2_license_notice` | — |
| `translation_language_unsupported` | `/run/translation_language_unsupported` | — |
| `download_progress_whisper_weight` | `/run/download_progress_whisper_weight` | useTranscription.updateDownloadProgressWhisperWeightTypeStatus |
| `downloaded_whisper_weight` | `/run/downloaded_whisper_weight` | useTranscription.downloadedWhisperWeightTypeStatus |
| `error_whisper_weight` | `/run/error_whisper_weight` | — |
| `selected_mic_host` | `/run/selected_mic_host` | useDevice.updateFromBackendSelectedMicHost |
| `selected_mic_device` | `/run/selected_mic_device` | useDevice.updateFromBackendSelectedMicDevice |
| `selected_speaker_device` | `/run/selected_speaker_device` | useDevice.updateFromBackendSelectedSpeakerDevice |
| `selected_translation_engines` | `/run/selected_translation_engines` | useLanguageSettings.updateSelectedTranslationEngines |
| `translation_engines` | `/run/translation_engines` | useLanguageSettings.updateTranslatorAvailability |
| `selected_your_languages` | `/run/selected_your_languages` | useLanguageSettings.updateSelectedYourLanguages |
| `selected_target_languages` | `/run/selected_target_languages` | useLanguageSettings.updateSelectedTargetLanguages |
| `selectable_language_list` | `/run/selectable_language_list` | useLanguageSettings.updateSelectableLanguageList |
| `selected_translation_compute_type` | `/run/selected_translation_compute_type` | useTranslation.updateFromBackendSelectedTranslationComputeType |
| `selected_transcription_compute_type` | `/run/selected_transcription_compute_type` | useTranscription.updateFromBackendSelectedTranscriptionComputeType |
| `selectable_plamo_model_list` | `/run/selectable_plamo_model_list` | useTranslation.updateFromBackendSelectablePlamoModelList |
| `selected_plamo_model` | `/run/selected_plamo_model` | useTranslation.updateFromBackendSelectedPlamoModel |
| `selectable_gemini_model_list` | `/run/selectable_gemini_model_list` | useTranslation.updateFromBackendSelectableGeminiModelList |
| `selected_gemini_model` | `/run/selected_gemini_model` | useTranslation.updateFromBackendSelectedGeminiModel |
| `selectable_openai_model_list` | `/run/selectable_openai_model_list` | useTranslation.updateFromBackendSelectableOpenAIModelList |
| `selected_openai_model` | `/run/selected_openai_model` | useTranslation.updateFromBackendSelectedOpenAIModel |
| `selectable_groq_model_list` | `/run/selectable_groq_model_list` | useTranslation.updateFromBackendSelectableGroqModelList |
| `selected_groq_model` | `/run/selected_groq_model` | useTranslation.updateFromBackendSelectedGroqModel |
| `selectable_openrouter_model_list` | `/run/selectable_openrouter_model_list` | useTranslation.updateFromBackendSelectableOpenRouterModelList |
| `selected_openrouter_model` | `/run/selected_openrouter_model` | useTranslation.updateFromBackendSelectedOpenRouterModel |
| `selectable_lmstudio_model_list` | `/run/selectable_lmstudio_model_list` | useTranslation.updateFromBackendSelectableLMStudioModelList |
| `selected_lmstudio_model` | `/run/selected_lmstudio_model` | useTranslation.updateFromBackendSelectedLMStudioModel |
| `selectable_openai_compatible_model_list` | `/run/selectable_openai_compatible_model_list` | useTranslation.updateFromBackendSelectableOpenAICompatibleModelList |
| `selected_openai_compatible_model` | `/run/selected_openai_compatible_model` | useTranslation.updateFromBackendSelectedOpenAICompatibleModel |
| `selectable_ollama_model_list` | `/run/selectable_ollama_model_list` | useTranslation.updateFromBackendSelectableOllamaModelList |
| `selected_ollama_model` | `/run/selected_ollama_model` | useTranslation.updateFromBackendSelectedOllamaModel |
| `selectable_groq_whisper_model_list` | `/run/selectable_groq_whisper_model_list` | useTranscription.updateFromBackendSelectableGroqWhisperModelList |
| `selected_groq_whisper_model` | `/run/selected_groq_whisper_model` | useTranscription.updateFromBackendSelectedGroqWhisperModel |
| `selectable_openai_whisper_model_list` | `/run/selectable_openai_whisper_model_list` | useTranscription.updateFromBackendSelectableOpenAIWhisperModelList |
| `selected_openai_whisper_model` | `/run/selected_openai_whisper_model` | useTranscription.updateFromBackendSelectedOpenAIWhisperModel |
| `selectable_custom_whisper_model_list` | `/run/selectable_custom_whisper_model_list` | useTranscription.updateFromBackendSelectableCustomWhisperModelList |
| `selected_custom_whisper_model` | `/run/selected_custom_whisper_model` | useTranscription.updateFromBackendSelectedCustomWhisperModel |
| `selectable_deepgram_model_list` | `/run/selectable_deepgram_model_list` | useTranscription.updateFromBackendSelectableDeepgramModelList |
| `selected_deepgram_model` | `/run/selected_deepgram_model` | useTranscription.updateFromBackendSelectedDeepgramModel |
| `overlay_small_log_settings` | `/run/overlay_small_log_settings` | useVr.updateFromBackendOverlaySmallLogSettings |
| `vr_panel_pointer` | `/run/vr_panel_pointer` | useVrPanelPointer.forwardVrPanelPointer |
| `vr_panel_log_out_of_view` | `/run/vr_panel_log_out_of_view` | useVrPanelLogOutOfView.updateVrPanelLogOutOfView |
| `overlay_vr_launcher_hand` | `/run/overlay_vr_launcher_hand` | useVr.updateFromBackendOverlayVrLauncherHand |
| `vr_panel_launcher_intro` | `/run/vr_panel_launcher_intro` | useVrPanelLauncherIntro.updateVrPanelLauncherIntro |
| `overlay_vr_panel_anchor` | `/run/overlay_vr_panel_anchor` | useVr.updateFromBackendOverlayVrPanelAnchor |
| `vr_panel_layout` | `/run/vr_panel_layout` | useVr.updateFromBackendVrPanelLayout |
| `overlay_large_log_settings` | `/run/overlay_large_log_settings` | useVr.updateFromBackendOverlayLargeLogSettings |
| `selectable_mic_host_list` | `/run/selectable_mic_host_list` | useDevice.updateFromBackendMicHostList |
| `selectable_mic_device_list` | `/run/selectable_mic_device_list` | useDevice.updateFromBackendMicDeviceList |
| `selectable_speaker_device_list` | `/run/selectable_speaker_device_list` | useDevice.updateFromBackendSpeakerDeviceList |
| `software_update_info` | `/run/software_update_info` | useSoftwareVersion.updateSoftwareVersionInfo |
| `initialization_progress` | `/run/initialization_progress` | useInitProgress.updateInitProgress |
| `initialization_complete` | `/run/initialization_complete` | — |
| `config_file_unreadable` | `/run/config_file_unreadable` | （受け取るだけ） |
| `config_save_failed` | `/run/config_save_failed` | （受け取るだけ） |
| `config_save_recovered` | `/run/config_save_recovered` | （受け取るだけ） |
| `enable_osc_query` | `/run/enable_osc_query` | useHandleOscQuery.handleOscQuery |


## UIに受信先がないエンドポイント（17件）

200で届いた場合にUIが`Invalid endpoint`としてコンソールに出すもの。ただし、400で届くエラーの通知（`/run/error_…`など）は`errorHandling_Backend`が処理し、`/run/initialization_complete`は`receiveRoutes`が個別に処理するので、このどちらかに当たるものは実害がない。

- `/run/ctranslate2_license_notice`
- `/run/enable_ocr_capture`
- `/run/enable_transcription_receive`
- `/run/enable_transcription_send`
- `/run/enable_translation`
- `/run/error_ctranslate2_weight`
- `/run/error_device`
- `/run/error_transcription_mic_vram_overflow`
- `/run/error_transcription_speaker_vram_overflow`
- `/run/error_translation_chat_vram_overflow`
- `/run/error_translation_enable_vram_overflow`
- `/run/error_translation_engine`
- `/run/error_translation_mic_vram_overflow`
- `/run/error_translation_speaker_vram_overflow`
- `/run/error_whisper_weight`
- `/run/initialization_complete`
- `/run/translation_language_unsupported`


## UIだけにあるルート（57件）

UIに受信先が定義されているが、サイドカーの`mapping`と`run_mapping`にはないもの。多くは`ui_config_setter.js`の定義が機械的に作るルートで、使われない。

- `/get/data/ctranslate2_weight`
- `/get/data/ollama_url`
- `/get/data/whisper_weight`
- `/run/pending_ctranslate2_weight`
- `/run/pending_whisper_weight`
- `/run/realtime_caption`
- `/set/data/auto_clear_message_box`
- `/set/data/auto_download_models`
- `/set/data/auto_mic_select`
- `/set/data/auto_speaker_select`
- `/set/data/clipboard`
- `/set/data/convert_message_to_hiragana`
- `/set/data/convert_message_to_romaji`
- `/set/data/ctranslate2_weight`
- `/set/data/logger_feature`
- `/set/data/mic_automatic_threshold`
- `/set/data/mic_vad_filter`
- `/set/data/notification_vrc_sfx`
- `/set/data/obs_browser_source`
- `/set/data/ocr_chatbox_filter`
- `/set/data/ocr_use_chatbox_detector`
- `/set/data/ollama_url`
- `/set/data/overlay_large_log`
- `/set/data/overlay_show_only_translated_messages`
- `/set/data/overlay_small_log`
- `/set/data/overlay_vr_launcher_auto_hide`
- `/set/data/overlay_vr_panel`
- `/set/data/overlay_vr_panel_locked`
- `/set/data/overlay_vr_tooltip`
- `/set/data/selectable_custom_whisper_model_list`
- `/set/data/selectable_deepgram_model_list`
- `/set/data/selectable_gemini_model_list`
- `/set/data/selectable_groq_model_list`
- `/set/data/selectable_groq_whisper_model_list`
- `/set/data/selectable_lmstudio_model_list`
- `/set/data/selectable_mic_device_list`
- `/set/data/selectable_mic_host_list`
- `/set/data/selectable_ocr_source_languages`
- `/set/data/selectable_ollama_model_list`
- `/set/data/selectable_openai_compatible_model_list`
- `/set/data/selectable_openai_model_list`
- `/set/data/selectable_openai_whisper_model_list`
- `/set/data/selectable_openrouter_model_list`
- `/set/data/selectable_plamo_model_list`
- `/set/data/selectable_speaker_device_list`
- `/set/data/selectable_transcription_compute_device_list`
- `/set/data/selectable_translation_compute_device_list`
- `/set/data/send_message_to_vrc`
- `/set/data/send_only_translated_messages`
- `/set/data/send_received_message_to_vrc`
- `/set/data/show_resend_button`
- `/set/data/speaker_automatic_threshold`
- `/set/data/speaker_vad_filter`
- `/set/data/telemetry`
- `/set/data/vrc_mic_mute_sync`
- `/set/data/websocket_server`
- `/set/data/whisper_weight`
