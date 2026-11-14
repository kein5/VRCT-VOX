// Recovery never invokes a success handler: pending atoms already retain the
// last confirmed data. Only a terminal failure or process exit releases them.
export const restorePendingValue = value => value.state === "pending" ? { ...value, state: "ok" } : value;

// No optimistic completion: downloaded flags stay exactly as last confirmed.
export function restoreDownloadPending(value, request, all = false) {
    const id = typeof request === "object" && request !== null ? request.weight_type : request;
    let changed = false;
    const data = value.data.map(item => {
        if ((all || (id !== undefined && item.id === id)) && (item.is_pending || item.progress != null)) {
            changed = true;
            return { ...item, is_pending: false, progress: null };
        }
        return item;
    });
    const restored = restorePendingValue(value);
    return changed ? { ...restored, data } : restored;
}

export const staticPendingControls = {
    TranslationStatus: { endpoints: ["/set/enable/translation", "/set/disable/translation"] },
    TranscriptionSendStatus: { endpoints: ["/set/enable/transcription_send", "/set/disable/transcription_send"] },
    TranscriptionReceiveStatus: { endpoints: ["/set/enable/transcription_receive", "/set/disable/transcription_receive"] },
    OcrCaptureStatus: { endpoints: ["/set/enable/ocr_capture", "/set/disable/ocr_capture"] },
    MicThresholdCheckStatus: { endpoints: ["/set/enable/check_mic_threshold", "/set/disable/check_mic_threshold"] },
    SpeakerThresholdCheckStatus: { endpoints: ["/set/enable/check_speaker_threshold", "/set/disable/check_speaker_threshold"] },
    IsLMStudioConnected: { endpoints: ["/run/lmstudio_connection", "/get/data/connected_lmstudio"], read: "/get/data/connected_lmstudio" },
    IsOllamaConnected: { endpoints: ["/run/ollama_connection", "/get/data/connected_ollama"], read: "/get/data/connected_ollama" },
    Hotkeys: { endpoints: ["/get/data/hotkeys", "/set/data/hotkeys"], read: "/get/data/hotkeys" },
    AvailableReleases: { endpoints: ["/get/data/available_releases"] },
    SoftwareVersion: { endpoints: ["/get/data/version"] },
};

// This legacy UI entry has no GET in mainloop.mapping.
const settingsWithoutRead = new Set(["ollama_url"]);

export function settingPendingControl(setting) {
    const name = setting.base_endpoint_name;
    // Keep per-item progress/completion; failures identify just the refused item.
    if (setting.logics_template_id === "weight_download_status") {
        const read = `/get/data/selectable_${name}_type_dict`;
        return { endpoints: [`/run/download_${name}`, read], read, download: true, parallel: true };
    }
    const read = `/get/data/${name}`;
    const endpoints = [read];
    if (setting.logics_template_id === "toggle_enable_disable") {
        endpoints.push(`/set/enable/${name}`, `/set/disable/${name}`);
    } else if (!["get_only", "get_list"].includes(setting.logics_template_id)) {
        endpoints.push(`/set/data/${name}`);
        if (setting.logics_template_id === "get_set_delete") endpoints.push(`/delete/data/${name}`);
    }
    return { endpoints, read: settingsWithoutRead.has(name) ? undefined : read };
}

// Feature-specific handlers still own their errors and generations. These
// setting writes additionally need a read after an exception may partly apply.
export const featureResyncReads = {
    "/set/data/voice_settings": "/get/data/voice_settings",
    "/set/data/speech_server_settings": "/get/data/speech_server_settings",
    "/set/data/realtime_asr_settings": "/get/data/realtime_asr_settings",
    "/run/start_model_download": "/get/data/model_download_state",
    "/run/cancel_model_download": "/get/data/model_download_state",
    "/run/apply_model_download": "/get/data/model_download_state",
    "/run/refresh_model_download_hardware": "/get/data/model_download_hardware",
};

export function createPendingRequestRecovery() {
    const controls = new Map(), restorers = new Set(), reads = new Map();
    const register = ({ endpoints = [], read, restore, stop = restore, parallel = false }) => {
        restorers.add(stop);
        const control = { read, restore, version: 0, parallel };
        for (const endpoint of endpoints) controls.set(endpoint, control);
    };
    const beginSend = endpoint => {
        const control = controls.get(endpoint);
        if (control && endpoint !== control.read) control.version++;
        return control?.version;
    };
    const failSend = (endpoint, value, version) => {
        const control = controls.get(endpoint);
        if (!control || (!control.parallel && version !== undefined && control.version !== version)) return false;
        return control.restore(value, false, !endpoint.startsWith("/get/"));
    };
    const resync = (control, send) => {
        const previous = reads.get(control.read);
        if (previous) { previous.again = () => resync(control, send); return; }
        const reading = { control, version: control.version };
        reads.set(control.read, reading);
        const failed = () => {
            if (reads.get(control.read) !== reading) return;
            reads.delete(control.read);
            reading.again?.();
        };
        try { Promise.resolve(send(control.read)).then(sent => { if (sent === false) failed(); }, failed); }
        catch { failed(); }
    };
    const acceptResponse = endpoint => {
        const reading = reads.get(endpoint);
        if (!reading) return true;
        reads.delete(endpoint);
        if (reading.again) { reading.again(); return false; }
        // A recovery GET may overtake a later write. Do not clear that write's
        // pending state or replace its value with the older read's result.
        return reading.version === reading.control.version;
    };
    const receive = ({ endpoint, status, result }, send) => {
        // 403: the backend refused a request relayed for the VR panel (models/vr_panel_policy.py).
        if (![403, 404, 423, 500].includes(status)) return;
        const control = controls.get(endpoint);
        if (!control) return;
        control.restore(result?.data, false, true);
        // Never retry a write, nor recursively retry a failed recovery GET.
        if (status === 500 && control.read && control.read !== endpoint) {
            resync(control, send);
        }
    };
    return { register, beginSend, failSend, acceptResponse, receive, stop: () => {
        reads.clear();
        restorers.forEach(restore => restore());
    } };
}

export const pendingRequestRecovery = createPendingRequestRecovery();

// Both sync throws and rejected writes have the same failure path. This wrapper
// also covers encoding/VR relay failures, before a child.write promise exists.
export async function sendWithRecovery(send, failed) {
    try {
        const sent = await send();
        if (sent !== false) return sent;
    } catch (error) {
        console.error("Sidecar send failed", error);
    }
    failed();
    return false;
}
