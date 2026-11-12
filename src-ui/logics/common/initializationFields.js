const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
const string = value => typeof value === "string";
const boolean = value => typeof value === "boolean";
const number = value => typeof value === "number" && Number.isFinite(value);
const tabs = ["1", "2", "3"];
// Unknown languages render the existing loading label without inventing a
// backend selection. Every slot the selector indexes must exist before ready.
export const initialLanguages = (target = false) => Object.fromEntries(tabs.map(tab => [tab,
    Object.fromEntries((target ? tabs : ["1"]).map(slot => [slot, { language: "", country: "", enable: slot === "1" }]))]));
const matches = fallback => value => {
    if (fallback == null) return value === null || record(value);
    if (Array.isArray(fallback)) return Array.isArray(value);
    if (record(fallback)) return record(value) && Object.entries(fallback).every(([key, item]) => matches(item)(value[key]));
    return typeof fallback === "number" ? number(value) : typeof value === typeof fallback;
};

export const createInitializationValidators = settings => {
    const validators = {};
    for (const setting of settings) {
        const name = setting.base_endpoint_name;
        if (setting.logics_template_id === "weight_download_status") {
            validators[`/get/data/selectable_${name}_type_dict`] = record;
            continue;
        }
        const validate = setting.response_transform ? Array.isArray : matches(setting.default_value);
        const optional = name.endsWith("_auth_key") || /^selected_.*_model$/.test(name) || name === "selected_transcription_engine";
        validators[`/get/data/${name}`] = optional ? value => value === null || validate(value) : validate;
    }
    const specific = {
        selected_your_languages: matches(initialLanguages()),
        selected_target_languages: matches(initialLanguages(true)),
        selected_translation_engines: matches({ 1: "", 2: "", 3: "" }),
        selected_tab_no: value => tabs.includes(value),
        selectable_translation_engines: Array.isArray,
        selectable_language_list: Array.isArray,
        selected_translation_compute_device: record,
        selected_transcription_compute_device: record,
        hotkeys: value => record(value) && ["open_quick_chat", "toggle_vrct_visibility", "toggle_translation",
            "toggle_transcription_send", "toggle_transcription_receive",
            "stop_voice", "toggle_voice_mute", "toggle_tts", "toggle_rvc"].every(key =>
            value[key] === null || (Array.isArray(value[key]) && value[key].every(string))),
        compute_mode: string,
        version: string,
        message_box_ratio: number,
        foreground: boolean,
        main_window_sidebar_compact_mode: boolean,
        connected_lmstudio: boolean,
        connected_ollama: boolean,
        main_window_geometry: matches({ x_pos: 0, y_pos: 0, width: 0, height: 0 }),
        available_releases: Array.isArray,
    };
    for (const name of ["voice_settings", "voice_status", "voice_route", "voice_output_devices", "tts_model_options",
        "direct_voice_state", "direct_voice_sources", "speech_server_settings", "speech_server_state",
        "realtime_asr_settings", "realtime_asr_state", "realtime_asr_models", "realtime_asr_endpoints",
        "model_download_catalog", "model_download_state", "model_download_hardware"]) specific[name] = record;
    for (const [name, validate] of Object.entries(specific)) validators[`/get/data/${name}`] = validate;
    return validators;
};

// Null remains valid for optional credentials/models. Failed required getters
// keep their safe UI defaults and participate in the degraded-startup warning.
export const applyInitializationFields = (result, routes, validators, invalidEndpoint) => {
    const failed = [];
    const report = (endpoint, reason) => {
        failed.push(endpoint);
        // Getter values can contain credentials. Log the name and reason only.
        console.error("Sidecar initialization field unavailable", endpoint, reason);
    };
    if (!result || typeof result !== "object" || Array.isArray(result)) {
        report("/run/initialization_complete", "expected an object");
        return failed;
    }
    for (const [endpoint, value] of Object.entries(result)) {
        if (!Object.hasOwn(routes, endpoint)) {
            invalidEndpoint({ endpoint, result: value });
            continue;
        }
        if (validators[endpoint] && !validators[endpoint](value)) {
            report(endpoint, value == null ? "missing value" : "invalid value shape");
            continue;
        }
        try {
            routes[endpoint](value);
        } catch {
            report(endpoint, "could not apply value");
        }
    }
    return failed;
};
