import { store } from "@store";

import {
    useStore_TranslationStatus,
    useStore_TranscriptionSendStatus,
    useStore_TranscriptionReceiveStatus,
    useStore_OcrCaptureStatus,
    useStore_ForegroundStatus,
} from "@store";
import { useStdoutToPython } from "@useStdoutToPython";

export const useMainFunction = () => {
    const appWindow = store.appWindow;

    const {
        currentTranslationStatus,
        updateTranslationStatus,
        pendingTranslationStatus,
    } = useStore_TranslationStatus();
    const {
        currentTranscriptionSendStatus,
        updateTranscriptionSendStatus,
        pendingTranscriptionSendStatus,
    } = useStore_TranscriptionSendStatus();
    const {
        currentTranscriptionReceiveStatus,
        updateTranscriptionReceiveStatus,
        pendingTranscriptionReceiveStatus,
    } = useStore_TranscriptionReceiveStatus();
    const {
        currentOcrCaptureStatus,
        updateOcrCaptureStatus,
        pendingOcrCaptureStatus,
    } = useStore_OcrCaptureStatus();
    const {
        currentForegroundStatus,
        updateForegroundStatus,
        pendingForegroundStatus,
    } = useStore_ForegroundStatus();

    const { asyncStdoutToPython } = useStdoutToPython();

    const createTogglePair = (pendingFn, updateFn, endpointName) => {
        // intent says why, when it is not the user pressing the switch: settings
        // pause the inputs while they are open ({ reason: "settings_pause" }) and
        // bring them back on leaving ({ reason: "settings_resume" }).
        const setFn = (to_enable, intent) => {
            if (!store.is_vr_panel && (!store.backend_subprocess || store.backend_stopped)) return;
            pendingFn();
            if (to_enable) {
                asyncStdoutToPython(`/set/enable/${endpointName}`, intent);
            } else {
                asyncStdoutToPython(`/set/disable/${endpointName}`, intent);
            }
        };
        const toggleFn = () => {
            if (!store.is_vr_panel && (!store.backend_subprocess || store.backend_stopped)) return;
            // updater は data を返す必要がある(returnしないとdataがundefinedになる)。
            // またsetFn(バックエンドへの送信という副作用)はupdater内で呼ばず、
            // dataを変更せずstateのみpendingにしてから同期的に外側で呼び出す。
            let next_enabled;
            updateFn(prev_state => {
                if (prev_state.state === "ok") {
                    next_enabled = !prev_state.data;
                }
                return prev_state.data;
            }, { set_state: "pending" });
            if (next_enabled !== undefined) {
                setFn(next_enabled);
            }
        };
        return { setFn, toggleFn };
    };

    const { setFn: setTranslation, toggleFn: toggleTranslation } = createTogglePair(
        pendingTranslationStatus, updateTranslationStatus, "translation"
    );
    const { setFn: setTranscriptionSend, toggleFn: toggleTranscriptionSend } = createTogglePair(
        pendingTranscriptionSendStatus, updateTranscriptionSendStatus, "transcription_send"
    );
    const { setFn: setTranscriptionReceive, toggleFn: toggleTranscriptionReceive } = createTogglePair(
        pendingTranscriptionReceiveStatus, updateTranscriptionReceiveStatus, "transcription_receive"
    );
    const { setFn: setOcrCapture, toggleFn: toggleOcrCapture } = createTogglePair(
        pendingOcrCaptureStatus, updateOcrCaptureStatus, "ocr_capture"
    );


    const toggleForeground = async () => {
        if (currentForegroundStatus.state === "pending") return;
        pendingForegroundStatus();
        const is_foreground_enabled = !currentForegroundStatus.data;
        try {
            await appWindow.setAlwaysOnTop(is_foreground_enabled);
            updateForegroundStatus(is_foreground_enabled);
            // The window is already changed; the sidecar only remembers it for the next start.
            asyncStdoutToPython(is_foreground_enabled ? "/set/enable/foreground" : "/set/disable/foreground");
        } catch (e) {
            updateForegroundStatus(currentForegroundStatus.data);
            console.error(e);
        }
    };

    // The saved value from /run/initialization_complete: put the window back on top.
    const restoreForeground = async (is_foreground_enabled) => {
        if (is_foreground_enabled !== true) {
            updateForegroundStatus(false);
            return;
        }
        try {
            await appWindow.setAlwaysOnTop(true);
            updateForegroundStatus(true);
        } catch (e) {
            updateForegroundStatus(false);
            console.error(e);
        }
    };

    return {
        currentTranslationStatus,
        toggleTranslation,
        updateTranslationStatus,
        setTranslation,
        pendingTranslationStatus, // Exception.(It shouldn't be used in other function, normally.)

        currentTranscriptionSendStatus,
        toggleTranscriptionSend,
        updateTranscriptionSendStatus,
        setTranscriptionSend,
        pendingTranscriptionSendStatus, // Exception.(It shouldn't be used in other function, normally.)

        currentTranscriptionReceiveStatus,
        toggleTranscriptionReceive,
        updateTranscriptionReceiveStatus,
        setTranscriptionReceive,
        pendingTranscriptionReceiveStatus, // Exception.(It shouldn't be used in other function, normally.)

        currentOcrCaptureStatus,
        toggleOcrCapture,
        updateOcrCaptureStatus,
        setOcrCapture,
        pendingOcrCaptureStatus, // Exception.(It shouldn't be used in other function, normally.)

        currentForegroundStatus,
        toggleForeground,
        restoreForeground,
        updateForegroundStatus,

    };
};
