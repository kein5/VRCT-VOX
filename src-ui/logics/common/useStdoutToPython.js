import { store } from "@store";
import { encode } from "js-base64";
import { useNotificationStatus } from "./useNotificationStatus";
import { useI18n } from "@useI18n";
import { pendingRequestRecovery, sendWithRecovery } from "./pendingRequestRecovery.js";
import { emit } from "@tauri-apps/api/event";
import { isLanguageMutation, beginLanguageMutation, createLanguageRequestId, getLanguageSnapshot,
    failLanguageMutationBeforeSend, failLanguageRead, languageMutationWriteUnconfirmed } from "../main/languageMutations";

export const useStdoutToPython = () => {
    const { showNotification_Error } = useNotificationStatus();
    const { t } = useI18n();
    const asyncStdoutToPython = async (path, value = undefined, languageRequest = undefined) => {
        const is_language_write = isLanguageMutation(path);
        const request = is_language_write ? { ...languageRequest, endpoint: path,
            requestId: languageRequest?.requestId ?? createLanguageRequestId(),
            source: languageRequest?.source ?? (store.is_vr_panel ? "vr" : "pc"),
            expectedSnapshot: languageRequest?.expectedSnapshot ?? getLanguageSnapshot() } : undefined;
        const pendingVersion = pendingRequestRecovery.beginSend(path);
        let writeAttempted = false, languageRejected = false;
        const exitExpected = store.backend_exit_expected;
        const exitsBackend = path === "/run/shutdown" || path === "/run/update_software";
        return sendWithRecovery(async () => {
            // The main window owns the sidecar and restores mirrored atoms on failure.
            if (store.is_vr_panel) {
                await emit("vr-panel-stdout", { path, value, languageRequest: request });
                return true;
            }
            if (is_language_write && !beginLanguageMutation(request)) {
                languageRejected = true;
                return false;
            }
            const send_object = { endpoint: path };
            if (value !== undefined) send_object.data = encode(JSON.stringify(value));
            const backend_subprocess = store.backend_subprocess;
            if (!backend_subprocess) return false;
            if (exitsBackend) store.backend_exit_expected = true;
            writeAttempted = true;
            return await backend_subprocess.write(JSON.stringify(send_object) + "\n") !== false;
        }, () => {
            if (languageRejected) return;
            if (exitsBackend) store.backend_exit_expected = exitExpected;
            if (is_language_write) {
                // Preserve language ownership when a write may have reached Python.
                if (writeAttempted) languageMutationWriteUnconfirmed(request.requestId);
                else failLanguageMutationBeforeSend(request.requestId);
            } else failLanguageRead(path);
            const restored = pendingRequestRecovery.failSend(path, value, pendingVersion);
            if (restored && !store.backend_stopped) {
                showNotification_Error(t("common_error.request_send_failed"), { category_id: "request_send_failed" });
            }
        });
    };
    return { asyncStdoutToPython };
};
