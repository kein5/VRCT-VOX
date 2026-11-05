import { store } from "@store";
import { useEffect } from "react";
import { useI18n } from "@useI18n";
import * as realtime from "./transcription/useRealtimeASR";
import * as common from "@logics_common";
import * as main from "@logics_main";
import * as configs from "@logics_configs";
import * as voice from "./voice/useVoice";
import * as speech from "./voice/useSpeechServers";
import * as downloads from "./voice/useModelDownloads";
import { _useBackendErrorHandling } from "./_useBackendErrorHandling";
import { SETTINGS_ARRAY } from "./configs/config_page_setter/ui_config_setter";
import { useStdoutToPython } from "@useStdoutToPython";
import { pendingRequestRecovery, featureResyncReads } from "./common/pendingRequestRecovery.js";
import { receiveLanguageMutation, resetLanguageMutations, isLanguageMutation } from "./main/languageMutations";
import { applyInitializationFields } from "./common/initializationFields.js";
import { isBackendUpdate, rejectExpectedExit } from "./common/sidecarExitExpectation.js";

const INIT_ARRAY_FIELDS = new Set(SETTINGS_ARRAY
    .filter(setting => ["arrayToObject", "arrayToIdLabel", "transformToIndexedArray", "deviceOptionsToObject"].includes(setting.response_transform))
    .map(setting => `/get/data/${setting.base_endpoint_name}`));

export const STATIC_ROUTE_META_LIST = [
    { endpoint: "/get/data/model_download_catalog", ns: downloads, hook_name: "useModelDownloads", method_name: "updateCatalog" },
    { endpoint: "/get/data/model_download_hardware", ns: downloads, hook_name: "useModelDownloads", method_name: "updateHardware" },
    { endpoint: "/run/refresh_model_download_hardware", ns: downloads, hook_name: "useModelDownloads", method_name: "updateHardware" },
    { endpoint: "/get/data/model_download_state", ns: downloads, hook_name: "useModelDownloads", method_name: "updateState" },
    { endpoint: "/run/start_model_download", ns: downloads, hook_name: "useModelDownloads", method_name: "acknowledge" },
    { endpoint: "/run/cancel_model_download", ns: downloads, hook_name: "useModelDownloads", method_name: "acknowledge" },
    { endpoint: "/run/apply_model_download", ns: downloads, hook_name: "useModelDownloads", method_name: "acknowledge" },
    { endpoint: "/get/data/speech_server_settings", ns: speech, hook_name: "useSpeechServers", method_name: "updateSettings" },
    { endpoint: "/set/data/speech_server_settings", ns: speech, hook_name: "useSpeechServers", method_name: "updateSettings" },
    { endpoint: "/get/data/speech_server_state", ns: speech, hook_name: "useSpeechServers", method_name: "updateState" },
    { endpoint: "/run/start_speech_server", ns: speech, hook_name: "useSpeechServers", method_name: "updateState" },
    { endpoint: "/run/stop_speech_server", ns: speech, hook_name: "useSpeechServers", method_name: "updateState" },
    { endpoint: "/get/data/realtime_asr_settings", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateSettings" },
    { endpoint: "/set/data/realtime_asr_settings", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateSettings" },
    { endpoint: "/get/data/realtime_asr_endpoints", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateEndpoints" },
    { endpoint: "/get/data/realtime_asr_models", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateModels" },
    { endpoint: "/get/data/realtime_asr_state", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateState" },
    { endpoint: "/run/start_realtime_asr", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateState" },
    { endpoint: "/run/stop_realtime_asr", ns: realtime, hook_name: "useRealtimeASR", method_name: "updateState" },
    { endpoint: "/run/realtime_caption", ns: common, hook_name: "useMessage", method_name: "updateRealtimeCaption" },
    { endpoint: "/get/data/tts_model_options", ns: voice, hook_name: "useVoice", method_name: "updateModelOptions" },
    { endpoint: "/get/data/voice_settings", ns: voice, hook_name: "useVoice", method_name: "updateSettings" },
    { endpoint: "/set/data/voice_settings", ns: voice, hook_name: "useVoice", method_name: "updateSettings" },
    { endpoint: "/get/data/voice_status", ns: voice, hook_name: "useVoice", method_name: "updateStatus" },
    { endpoint: "/get/data/voice_output_devices", ns: voice, hook_name: "useVoice", method_name: "updateDevices" },
    { endpoint: "/run/enable_tts", ns: voice, hook_name: "useVoice", method_name: "updateStatus" },
    { endpoint: "/run/disable_tts", ns: voice, hook_name: "useVoice", method_name: "updateStatus" },
    { endpoint: "/run/stop_voice", ns: voice, hook_name: "useVoice", method_name: "updateStatus" },
    { endpoint: "/get/data/voice_route", ns: voice, hook_name: "useVoice", method_name: "updateRoute" },
    { endpoint: "/run/mute_voice", ns: voice, hook_name: "useVoice", method_name: "updateRoute" },
    { endpoint: "/run/resume_voice", ns: voice, hook_name: "useVoice", method_name: "updateRoute" },
    { endpoint: "/get/data/direct_voice_sources", ns: voice, hook_name: "useVoice", method_name: "updateDirectSources" },
    { endpoint: "/set/data/direct_voice_settings", ns: voice, hook_name: "useVoice", method_name: "updateDirectState" },
    { endpoint: "/get/data/direct_voice_state", ns: voice, hook_name: "useVoice", method_name: "updateDirectState" },
    { endpoint: "/run/start_direct_voice", ns: voice, hook_name: "useVoice", method_name: "updateDirectState" },
    { endpoint: "/run/stop_direct_voice", ns: voice, hook_name: "useVoice", method_name: "updateDirectState" },
    // Common
    { endpoint: "/run/feed_watchdog", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/initialization_progress", ns: common, hook_name: "useInitProgress", method_name: "updateInitProgress" },
    { endpoint: "/run/enable_ai_models", ns: common, hook_name: "useIsVrctAvailable", method_name: "handleAiModelsAvailability" },
    { endpoint: "/get/data/compute_mode", ns: common, hook_name: "useComputeMode", method_name: "updateComputeMode" },

    { endpoint: "/run/update_software", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/audio_device_switched", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/config_file_unreadable", ns: null, hook_name: null, method_name: null }, // Shown by receiveRoutes itself.
    { endpoint: "/run/config_save_failed", ns: null, hook_name: null, method_name: null }, // Shown by receiveRoutes itself.
    // Fire-and-forget actions from the VR settings (sample text, sent repeatedly while
    // started, and launcher reset): the answer needs no handling, but without a route
    // each one was logged as an invalid endpoint.
    { endpoint: "/run/send_text_overlay", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/vr_launcher_reset", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/config_save_recovered", ns: null, hook_name: null, method_name: null }, // Shown by receiveRoutes itself.

    // VR UI のポインタ位置 (ホバー表示用)。VR ウィンドウへ転送する
    { endpoint: "/run/vr_panel_pointer", ns: common, hook_name: "useVrPanelPointer", method_name: "forwardVrPanelPointer" },
    // VR UI のウィンドウ開閉の応答 (VR画面が状態を持つので受け取るだけ)
    { endpoint: "/run/vr_panel_windows", ns: null, hook_name: null, method_name: null },
    // ログウィンドウが視線から外れた・戻った / 呼び戻しの応答
    { endpoint: "/run/vr_panel_log_out_of_view", ns: common, hook_name: "useVrPanelLogOutOfView", method_name: "updateVrPanelLogOutOfView" },
    { endpoint: "/run/vr_panel_launcher_intro", ns: common, hook_name: "useVrPanelLauncherIntro", method_name: "updateVrPanelLauncherIntro" },
    { endpoint: "/run/vr_panel_recall_log", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/vr_panel_layout_rendered", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/vr_panel_tooltip", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/update_cuda_software", ns: null, hook_name: null, method_name: null },

    { endpoint: "/get/data/main_window_geometry", ns: common, hook_name: "useWindow", method_name: "restoreWindowGeometry" },
    { endpoint: "/set/data/main_window_geometry", ns: null, hook_name: null, method_name: null },

    { endpoint: "/run/open_filepath_logs", ns: common, hook_name: "useOpenFolder", method_name: "openedFolder_MessageLogs" },
    { endpoint: "/run/open_filepath_config_file", ns: common, hook_name: "useOpenFolder", method_name: "openedFolder_ConfigFile" },

    { endpoint: "/get/data/connected_lmstudio", ns: common, hook_name: "useLLMConnection", method_name: "setConnectionStatus_LMStudio" },
    { endpoint: "/run/lmstudio_connection", ns: common, hook_name: "useLLMConnection", method_name: "setConnectionStatus_LMStudio" },

    { endpoint: "/get/data/connected_ollama", ns: common, hook_name: "useLLMConnection", method_name: "setConnectionStatus_Ollama" },
    { endpoint: "/run/ollama_connection", ns: common, hook_name: "useLLMConnection", method_name: "setConnectionStatus_Ollama" },

    // Software Version
    { endpoint: "/get/data/version", ns: common, hook_name: "useSoftwareVersion", method_name: "updateSoftwareVersion" },
    { endpoint: "/get/data/available_releases", ns: common, hook_name: "useAvailableReleases", method_name: "updateAvailableReleasesFromBackend" },
    // Latest Software Version Info
    { endpoint: "/run/software_update_info", ns: common, hook_name: "useSoftwareVersion", method_name: "updateSoftwareVersionInfo" },

    { endpoint: "/run/connected_network", ns: common, hook_name: "useHandleNetworkConnection", method_name: "handleNetworkConnection" },
    { endpoint: "/run/enable_osc_query", ns: common, hook_name: "useHandleOscQuery", method_name: "handleOscQuery" },

    // Message (By typing)
    { endpoint: "/run/send_message_box", ns: common, hook_name: "useMessage", method_name: "updateSentMessageLogById" },
    { endpoint: "/run/typing_message_box", ns: null, hook_name: null, method_name: null },
    { endpoint: "/run/stop_typing_message_box", ns: null, hook_name: null, method_name: null },
    // Message Transcription
    { endpoint: "/run/transcription_send_mic_message", ns: common, hook_name: "useMessage", method_name: "addSentMessageLog" },
    { endpoint: "/run/transcription_receive_speaker_message", ns: common, hook_name: "useMessage", method_name: "addReceivedMessageLog" },
    { endpoint: "/run/transcription_ocr_message", ns: common, hook_name: "useMessage", method_name: "addReceivedMessageLog" },

    // System Messages
    { endpoint: "/run/word_filter", ns: common, hook_name: "useMessage", method_name: "addSystemMessageLog_FromBackend" },
    { endpoint: "/run/transcription_recognition_error", ns: common, hook_name: "useMessage", method_name: "addSystemMessageLog_FromBackend" },


    // Volume
    { endpoint: "/run/check_mic_volume", ns: common, hook_name: "useVolume", method_name: "updateVolumeVariable_Mic" },
    { endpoint: "/run/check_speaker_volume", ns: common, hook_name: "useVolume", method_name: "updateVolumeVariable_Speaker" },
    { endpoint: "/set/enable/check_mic_threshold", ns: common, hook_name: "useVolume", method_name: "updateMicThresholdCheckStatus" },
    { endpoint: "/set/disable/check_mic_threshold", ns: common, hook_name: "useVolume", method_name: "updateMicThresholdCheckStatus" },
    { endpoint: "/set/enable/check_speaker_threshold", ns: common, hook_name: "useVolume", method_name: "updateSpeakerThresholdCheckStatus" },
    { endpoint: "/set/disable/check_speaker_threshold", ns: common, hook_name: "useVolume", method_name: "updateSpeakerThresholdCheckStatus" },




    // Main Page
    // Page Controls
    { endpoint: "/get/data/main_window_sidebar_compact_mode", ns: main, hook_name: "useIsMainPageCompactMode", method_name: "updateIsMainPageCompactMode" },
    { endpoint: "/get/data/foreground", ns: main, hook_name: "useMainFunction", method_name: "restoreForeground" },
    { endpoint: "/set/enable/foreground", ns: main, hook_name: "useMainFunction", method_name: "updateForegroundStatus" },
    { endpoint: "/set/disable/foreground", ns: main, hook_name: "useMainFunction", method_name: "updateForegroundStatus" },
    { endpoint: "/set/enable/main_window_sidebar_compact_mode", ns: main, hook_name: "useIsMainPageCompactMode", method_name: "updateIsMainPageCompactMode" },
    { endpoint: "/set/disable/main_window_sidebar_compact_mode", ns: main, hook_name: "useIsMainPageCompactMode", method_name: "updateIsMainPageCompactMode" },

    // Main Functions
    { endpoint: "/set/enable/translation", ns: main, hook_name: "useMainFunction", method_name: "updateTranslationStatus" },
    { endpoint: "/set/disable/translation", ns: main, hook_name: "useMainFunction", method_name: "updateTranslationStatus" },
    { endpoint: "/set/enable/transcription_send", ns: main, hook_name: "useMainFunction", method_name: "updateTranscriptionSendStatus" },
    { endpoint: "/set/disable/transcription_send", ns: main, hook_name: "useMainFunction", method_name: "updateTranscriptionSendStatus" },
    { endpoint: "/set/enable/transcription_receive", ns: main, hook_name: "useMainFunction", method_name: "updateTranscriptionReceiveStatus" },
    { endpoint: "/set/disable/transcription_receive", ns: main, hook_name: "useMainFunction", method_name: "updateTranscriptionReceiveStatus" },
    { endpoint: "/set/enable/ocr_capture", ns: main, hook_name: "useMainFunction", method_name: "updateOcrCaptureStatus" },
    { endpoint: "/set/disable/ocr_capture", ns: main, hook_name: "useMainFunction", method_name: "updateOcrCaptureStatus" },

    // Language Settings
    { endpoint: "/get/data/selected_tab_no", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedPresetTabNumber" },
    { endpoint: "/set/data/selected_tab_no", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedPresetTabNumber" },

    { endpoint: "/get/data/selected_your_languages", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedYourLanguages" },
    { endpoint: "/set/data/selected_your_languages", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedYourLanguages" },
    { endpoint: "/run/selected_your_languages", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedYourLanguages" },
    { endpoint: "/get/data/selected_target_languages", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedTargetLanguages" },
    { endpoint: "/set/data/selected_target_languages", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedTargetLanguages" },
    { endpoint: "/run/selected_target_languages", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedTargetLanguages" },

    { endpoint: "/get/data/selectable_translation_engines", ns: main, hook_name: "useLanguageSettings", method_name: "updateTranslatorAvailability" },
    { endpoint: "/run/translation_engines", ns: main, hook_name: "useLanguageSettings", method_name: "updateTranslatorAvailability" },

    { endpoint: "/get/data/selected_translation_engines", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedTranslationEngines" },
    { endpoint: "/set/data/selected_translation_engines", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedTranslationEngines" },
    { endpoint: "/run/selected_translation_engines", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectedTranslationEngines" },

    { endpoint: "/run/swap_your_language_and_target_language", ns: main, hook_name: "useLanguageSettings", method_name: "updateBothSelectedLanguages" },

    // Language Selector
    { endpoint: "/get/data/selectable_language_list", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectableLanguageList" },
    { endpoint: "/run/selectable_language_list", ns: main, hook_name: "useLanguageSettings", method_name: "updateSelectableLanguageList" },


    // Message Input Box
    { endpoint: "/get/data/message_box_ratio", ns: main, hook_name: "useMessageInputBoxRatio", method_name: "updateMessageInputBoxRatio" },
    { endpoint: "/set/data/message_box_ratio", ns: main, hook_name: "useMessageInputBoxRatio", method_name: "updateMessageInputBoxRatio" },


    // // Config Page
    // Hotkeys
    { endpoint: "/get/data/hotkeys", ns: configs, hook_name: "useHotkeys", method_name: "updateHotkeys" },
    { endpoint: "/set/data/hotkeys", ns: configs, hook_name: "useHotkeys", method_name: "setSuccessHotkeys" },

    // // Not Implemented.
    { endpoint: "/run/shutdown", ns: null, hook_name: null, method_name: null }, // Not implemented on UI.
    { endpoint: "/get/data/selectable_release_channels", ns: null, hook_name: null, method_name: null }, // Not implemented on UI yet; release_channel options are hardcoded in Updater.jsx for now.
];

const TRANSCRIPTION_TOGGLES = ["/set/enable/transcription_send", "/set/disable/transcription_send",
    "/set/enable/transcription_receive", "/set/disable/transcription_receive"];

export const useReceiveRoutes = () => {
    const { showNotification_Error, showNotification_Warning, showNotification_Success, dismissNotification } = common.useNotificationStatus();
    const { t, i18n } = useI18n();
    const { errorHandling_Backend } = _useBackendErrorHandling();
    const { settings: voiceSettings, status: voiceStatus, send: sendVoice, reset: resetVoice, backendStopped: stopVoicePending, updateTtsError, updateError: updateVoiceError, updateDirectError } = voice.useVoice();
    const voiceConnected = voiceSettings !== null;
    useEffect(() => {
        if (!voiceConnected) return;
        const poll = () => {
            if (store.backend_stopped) return;
            sendVoice("/get/data/voice_status");
            sendVoice("/get/data/voice_route");
            sendVoice("/get/data/direct_voice_state");
        };
        poll();
        const timer = setInterval(poll, 1000);
        return () => clearInterval(timer);
    }, [voiceConnected, sendVoice]);
    const { state: speechState, pending: speechPending, send: sendSpeech, updateError: updateSpeechError, reset: resetSpeech, backendStopped: stopSpeechPending } = speech.useSpeechServers();
    const speechActive = Object.values(speechState).some(row => ["preparing", "ready", "stopping"].includes(row.state)) || Object.keys(speechPending).length > 0
        || voiceStatus.tts_server_starting === true;
    useEffect(() => {
        if (!speechActive) return;
        const timer = setInterval(() => !store.backend_stopped && sendSpeech("/get/data/speech_server_state"), 500);
        return () => clearInterval(timer);
    }, [speechActive, sendSpeech]);
    const { state: downloadState, hardware: modelHardware, pending: downloadPending, send: sendDownload, updateError: updateDownloadError, reset: resetDownloads, backendStopped: stopDownloadPending } = downloads.useModelDownloads();
    useEffect(() => {
        if (modelHardware.phase !== 'probing') return;
        const timer = setInterval(() => !store.backend_stopped && sendDownload('/get/data/model_download_hardware'), 500);
        return () => clearInterval(timer);
    }, [modelHardware.phase, sendDownload]);
    const downloadActive = !!downloadPending || Object.values(downloadState.jobs).some(job => ["queued", "downloading", "verifying", "cancelling"].includes(job.phase));
    useEffect(() => {
        if (!downloadActive) return;
        const timer = setInterval(() => !store.backend_stopped && sendDownload("/get/data/model_download_state"), 750);
        return () => clearInterval(timer);
    }, [downloadActive, sendDownload]);
    useEffect(() => {
        if (!downloadPending) return;
        const timer = setTimeout(() => updateDownloadError("request_unconfirmed"), 10000);
        return () => clearTimeout(timer);
    }, [downloadPending, updateDownloadError]);
    const { state: realtimeState, send: sendRealtime, updateError: updateRealtimeError, reset: resetRealtime, backendStopped: stopRealtimePending } = realtime.useRealtimeASR();
    const realtimeActive = Object.values(realtimeState).some(value => value.requested);
    useEffect(() => {
        if (!realtimeActive) return;
        const timer = setInterval(() => !store.backend_stopped && sendRealtime("/get/data/realtime_asr_state"), 500);
        return () => clearInterval(timer);
    }, [realtimeActive, sendRealtime]);
    const { updateIsBackendReady } = common.useIsBackendReady();
    const { updateIsSoftwareUpdating } = common.useIsSoftwareUpdating();
    const { asyncStdoutToPython } = useStdoutToPython();

    const handleInvalidEndpoint = (parsed_data) => {
        console.error(`Invalid endpoint: ${parsed_data.endpoint}\nresult: ${JSON.stringify(parsed_data.result)}`);
    };

    const hook_results = {};
    ROUTE_META_LIST.forEach(({ ns, hook_name }) => {
        if (ns && hook_name && !(hook_name in hook_results)) {
            const hookFn = ns[hook_name];
            if (typeof hookFn === "function") {
                hook_results[hook_name] = hookFn();
            } else {
                console.warn(`Hook not found on namespace: ${hook_name}`);
                hook_results[hook_name] = {};
            }
        }
    });

    const noop = () => {};

    const routes = Object.fromEntries(
        ROUTE_META_LIST.map(({ endpoint, hook_name, method_name }) => {
            const result_obj = hook_results[hook_name] || {};
            const fn = result_obj[method_name];
            if (fn === undefined && method_name !== null) {
                console.error("Method not found.", { endpoint, hook_name, method_name, result_obj, fn });
            }
            return [endpoint, typeof fn === "function"
                ? (hook_name === "useModelDownloads" && method_name === "acknowledge" ? value => fn(value, endpoint) : fn)
                : noop];
        })
    );


    const receiveRoutes = (parsed_data) => {
        const { endpoint = "", status, result } = parsed_data;
        if (status !== 200 && (isBackendUpdate(endpoint) || endpoint === "/run/shutdown")) {
            rejectExpectedExit(store.backend_session, endpoint);
            if (isBackendUpdate(endpoint)) updateIsSoftwareUpdating(false);
        }
        if (!pendingRequestRecovery.acceptResponse(endpoint)) return;
        pendingRequestRecovery.receive(parsed_data, asyncStdoutToPython);
        if (endpoint === "/run/send_message_box" && [400, 404, 423, 500].includes(status)) {
            hook_results.useMessage.failSentMessageLog(result?.data ?? result);
        }
        if (status === 500 && featureResyncReads[endpoint]) asyncStdoutToPython(featureResyncReads[endpoint]);
        if (status !== 200 && endpoint.includes("model_download")) {
            updateDownloadError(result?.error_code || "download_failed", endpoint);
            return;
        }
        // Enabling OBS also starts the WebSocket server it depends on.
        if (status === 200 && endpoint === "/set/enable/obs_browser_source") asyncStdoutToPython("/get/data/websocket_server");
        // On Linux the Device page Mic choice is the default RVC input (`preferred`).
        if (status === 200 && ["/set/data/selected_mic_host", "/set/data/selected_mic_device",
            "/run/selected_mic_host", "/run/selected_mic_device"].includes(endpoint)) {
            sendVoice("/get/data/direct_voice_sources");
        }
        if (status === 200 && endpoint === "/run/apply_model_download") {
            sendSpeech("/get/data/speech_server_settings");
            sendVoice("/get/data/direct_voice_state");
        }
        // The main TTS toggle can start or stop a bundled server; keep Settings in step.
        if (["/run/enable_tts", "/run/disable_tts"].includes(endpoint)) sendSpeech("/get/data/speech_server_state");
        if (status !== 200 && ["/run/enable_tts", "/run/disable_tts"].includes(endpoint)) {
            updateTtsError(result?.error_code || "voice_request_failed", endpoint, status);
            sendVoice("/get/data/voice_status");
            return;
        }
        if (status !== 200 && endpoint.includes("speech_server")) {
            updateSpeechError(result?.error_code || "speech_server_request_failed");
            if (endpoint !== "/get/data/speech_server_state") sendSpeech("/get/data/speech_server_state");
            return;
        }
        // On Linux these switches drive realtime ASR and may start or stop the
        // bundled ASR server; keep Settings in step with them.
        if (TRANSCRIPTION_TOGGLES.includes(endpoint)) {
            sendSpeech("/get/data/speech_server_state");
            sendRealtime("/get/data/realtime_asr_state");
        }
        if (status !== 200 && endpoint.includes("realtime_asr")) {
            updateRealtimeError(result?.error_code || "realtime_request_failed");
            return;
        }
        if (status !== 200 && endpoint.includes("direct_voice")) {
            updateDirectError(result?.error_code || "source_bridge_request_failed", endpoint, status);
            if ([404, 423, 500].includes(status) && endpoint !== "/get/data/direct_voice_state") sendVoice("/get/data/direct_voice_state");
            return;
        }
        if (status !== 200 && (endpoint.includes("/voice_") || ["/run/stop_voice", "/run/mute_voice", "/run/resume_voice"].includes(endpoint))) {
            updateVoiceError(result?.error_code || "voice_request_failed");
            return;
        }

        if (endpoint === "/run/initialization_complete") {
            resetDownloads();
            sendDownload("/get/data/model_download_catalog");
            sendDownload("/get/data/model_download_state");
            resetVoice();
            sendVoice("/get/data/voice_settings");
            sendVoice("/get/data/direct_voice_sources");
            resetSpeech();
            sendSpeech("/get/data/speech_server_settings");
            sendSpeech("/get/data/speech_server_state");
            resetRealtime();
            sendRealtime("/get/data/realtime_asr_settings");
            sendRealtime("/get/data/realtime_asr_state");
            for (const source of ["mic", "speaker"]) sendRealtime("/get/data/realtime_asr_endpoints", { source });
            const failedFields = applyInitializationFields(result, routes, INIT_ARRAY_FIELDS, handleInvalidEndpoint);
            updateIsBackendReady(true);
            resetLanguageMutations();
            if (failedFields.length > 0) {
                // The UI language from this same result is applied later by an effect.
                const language = result?.["/get/data/ui_language"];
                const translate = typeof language === "string" && i18n?.getFixedT ? i18n.getFixedT(language) : t;
                showNotification_Warning(translate("common_warning.startup_degraded"),
                    { hide_duration: null, category_id: "startup_degraded" });
            }
            return;
        }

        // config.json could not be read: the app runs on defaults and the old
        // file was kept beside it.
        if (status === 200 && endpoint === "/run/audio_device_switched") {
            if (["mic", "speaker"].includes(result?.source)
                && typeof result?.old_device?.name === "string" && typeof result?.new_device?.name === "string") {
                const sameName = result.old_device.name === result.new_device.name;
                const label = device => sameName && device.id ? `${device.name} (${device.id})` : device.name;
                showNotification_Warning(t(`common_warning.audio_device_switched.${result.source}`, {
                    old: label(result.old_device), new: label(result.new_device),
                }), { category_id: `audio_device_switched.${result.source}` });
            }
            return;
        }
        if (endpoint === "/run/config_save_failed") {
            // The change stays applied in memory; the sidecar keeps retrying the write.
            const reason = ["disk_full", "permission_denied", "read_only"].includes(result?.reason) ? result.reason : "write_failed";
            showNotification_Error(t(`common_error.config_save_failed.${reason}`, { file: result?.path ?? "" }),
                { hide_duration: null, category_id: "config_save_failed" });
            return;
        }
        if (endpoint === "/run/config_save_recovered") {
            dismissNotification("config_save_failed");
            showNotification_Success(t("common_error.config_save_failed.recovered"), { category_id: "config_save_recovered" });
            return;
        }
        if (endpoint === "/run/config_file_unreadable") {
            showNotification_Warning(t("common_warning.config_file_unreadable", { file: result?.backup ?? "" }),
                { hide_duration: null, category_id: "config_file_unreadable" });
            return;
        }

        if (status !== 200) receiveLanguageMutation(parsed_data, asyncStdoutToPython);

        switch (status) {
            case 200:
                if (endpoint in routes) {
                    routes[endpoint](result);
                } else {
                    handleInvalidEndpoint(parsed_data);
                }
                receiveLanguageMutation(parsed_data, asyncStdoutToPython);
                break;

            case 400:
                errorHandling_Backend({
                    error_code: parsed_data.result.error_code,
                    message: parsed_data.result.message,
                    data: parsed_data.result.data,
                    endpoint: parsed_data.endpoint,
                    result: parsed_data.result,
                });
                break;

            case 348:
                // console.log(`from backend: %c ${JSON.stringify(parsed_data)}`, style_348);
                break;

            case 404:
            case 423:
                // Language mutations already publish their own failure notice.
                if (!isLanguageMutation(endpoint)) showNotification_Error(t(`common_error.request_${status}`),
                    { category_id: `request_${status}` });
                console.error("Sidecar request rejected", parsed_data);
                break;

            case 500:
                console.error("Unexpected sidecar error", parsed_data);
                showNotification_Error(t("common_error.unexpected_error", { code: parsed_data.endpoint ?? "500" }), { hide_duration: null });
                break;

            default:
                console.log("Received data status does not match.", parsed_data);
        }
    };

    const backendStopped = () => {
        pendingRequestRecovery.stop();
        hook_results.useMessage.failSentMessageLog();
        resetLanguageMutations();
        stopVoicePending();
        stopSpeechPending();
        stopDownloadPending();
        stopRealtimePending();
    };
    return { receiveRoutes, backendStopped };
};

const style_348 = [
    "color: gray",
].join(";");



// Automatically set 'configs' for now.(This is only used in config)
const buildRouteMetaList = () => {
    const namespace_module = configs;
    const generated = [];

    for (const s of SETTINGS_ARRAY) {
        const category = s.Category;
        const base = s.Base_Name;
        const ep = s.base_endpoint_name;
        const hookName = `use${category}`;
        const setSuccessMethodName = `setSuccess${base}`;
        const deleteSuccessMethodName = `deleteSuccess${base}`;
        const updateFromBackendMethodName = `updateFromBackend${base}`;


        if (s.add_endpoint_run_array?.includes("from_backend")) {
            generated.push({
                endpoint: `/run/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: updateFromBackendMethodName,
            });
        }



        generated.push({
            endpoint: `/get/data/${ep}`,
            ns: namespace_module,
            hook_name: hookName,
            method_name: updateFromBackendMethodName,
        });

        if (s.logics_template_id === "get_set_delete") {
            generated.push({
                endpoint: `/delete/data/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: deleteSuccessMethodName,
            });
        }

        if (s.logics_template_id !== "get_list" && s.logics_template_id !== "get_only") {
            generated.push({
                endpoint: `/set/data/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: setSuccessMethodName,
            });
        }

        if (s.logics_template_id === "toggle_enable_disable" || s.ui_template_id === "toggle") {
            generated.push({
                endpoint: `/set/enable/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: setSuccessMethodName,
            });
            generated.push({
                endpoint: `/set/disable/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: setSuccessMethodName,
            });
        }

        if (s.logics_template_id === "weight_download_status") {
            generated.push({
                endpoint: `/get/data/selectable_${ep}_type_dict`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: `updateDownloaded${base}`,
            });

            generated.push({
                endpoint: `/set/data/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: setSuccessMethodName,
            });

            generated.push({
                endpoint: `/run/download_progress_${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: `updateDownloadProgress${base}`,
            });

            generated.push({
                endpoint: `/run/downloaded_${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: `downloaded${base}`,
            });
            generated.push({
                endpoint: `/run/pending_${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: `pending${base}`,
            });
            generated.push({
                endpoint: `/run/download_${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: `downloaded${base}`,
            });
            generated.push({
                endpoint: `/get/data/${ep}`,
                ns: namespace_module,
                hook_name: hookName,
                method_name: updateFromBackendMethodName,
            });
            continue;
        }
    }

    const mergedMap = new Map();

    for (const item of STATIC_ROUTE_META_LIST) {
        if (!item || !item.endpoint) continue;
        mergedMap.set(item.endpoint, {
            endpoint: item.endpoint,
            ns: item.ns ?? null,
            hook_name: item.hook_name ?? null,
            method_name: item.method_name ?? null,
        });
    }

    for (const gen of generated) {
        const ep = gen.endpoint;
        const existing = mergedMap.get(ep);
        if (!existing) {
            mergedMap.set(ep, { ...gen });
            continue;
        }

        const merged = {
            endpoint: ep,
            ns: existing.ns ?? gen.ns ?? null,
            hook_name: existing.hook_name ?? gen.hook_name ?? null,
            method_name: existing.method_name ?? gen.method_name ?? null,
        };
        mergedMap.set(ep, merged);
    }

    const mergedList = [];


    for (const item of STATIC_ROUTE_META_LIST) {
        if (!item || !item.endpoint) continue;
        const merged = mergedMap.get(item.endpoint);
        if (merged) {
            mergedList.push(merged);
            mergedMap.delete(item.endpoint);
        }
    }

    for (const gen of generated) {
        const ep = gen.endpoint;
        if (mergedMap.has(ep)) {
            mergedList.push(mergedMap.get(ep));
            mergedMap.delete(ep);
        }
    }

    for (const remaining of mergedMap.values()) {
        mergedList.push(remaining);
    }

    return mergedList;
};

const ROUTE_META_LIST = buildRouteMetaList();
