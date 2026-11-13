import { pendingRequestRecovery } from "./pendingRequestRecovery.js";

const endpoints = new Set([
    "voice_settings", "direct_voice_settings", "speech_server_settings", "realtime_asr_settings", "hotkeys",
    "openai_compatible_auth_key_and_url", "custom_whisper_auth_key_and_url",
    "overlay_small_log_settings", "overlay_large_log_settings",
    "mic_word_filter", "send_message_format_parts", "received_message_format_parts",
    "osc_ip_address", "osc_port", "websocket_host", "websocket_port",
    "obs_browser_source_port", "obs_browser_source_max_messages", "obs_browser_source_display_duration",
    "obs_browser_source_fadeout_duration", "obs_browser_source_font_size", "obs_browser_source_font_color",
    "obs_browser_source_font_outline_thickness", "obs_browser_source_font_outline_color",
].map(name => `/set/data/${name}`));
const textEndpoints = new Set([
    "deepl_auth_key", "plamo_auth_key", "gemini_auth_key", "openai_auth_key", "groq_auth_key", "openrouter_auth_key",
    "lmstudio_url", "openai_compatible_url", "openai_compatible_auth_key", "ollama_url",
    "groq_whisper_auth_key", "openai_whisper_auth_key", "custom_whisper_url", "custom_whisper_auth_key", "deepgram_auth_key",
].flatMap(name => [`/set/data/${name}`, `/delete/data/${name}`]));

// These setters reply in FIFO order. Keep timed-out owners until their reply:
// a GET or a later write must never confirm an earlier, uncertain save.
export function createSettingsWriteResponses() {
    const queues = new Map();
    const begin = endpoint => {
        if (!endpoints.has(endpoint) && !textEndpoints.has(endpoint)) return null;
        const queue = queues.get(endpoint) ?? [];
        // Delivery is unknown after a transport failure. A new response could
        // belong to either write, so wait for that reply or a session restart.
        if (queue.some(request => request.uncertain)) return false;
        const request = { endpoint };
        request.response = new Promise(resolve => { request.resolve = resolve; });
        queue.push(request);
        queues.set(endpoint, queue);
        return request;
    };
    const fail = (request, attempted) => {
        if (!request) return;
        request.resolve(false);
        request.uncertain = attempted;
        if (!attempted) {
            const queue = queues.get(request.endpoint);
            const index = queue?.indexOf(request) ?? -1;
            if (index >= 0) queue.splice(index, 1);
        }
    };
    const receive = response => {
        const queue = queues.get(response.endpoint);
        queue?.shift()?.resolve(response);
        if (!queue?.length) queues.delete(response.endpoint);
    };
    const stop = () => {
        for (const queue of queues.values()) for (const request of queue) request.resolve(false);
        queues.clear();
    };
    return { begin, fail, receive, stop };
}

export const settingsWriteResponses = createSettingsWriteResponses();
pendingRequestRecovery.register({ stop: settingsWriteResponses.stop });
