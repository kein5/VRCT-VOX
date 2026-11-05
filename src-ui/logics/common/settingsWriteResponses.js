import { pendingRequestRecovery } from "./pendingRequestRecovery.js";

const endpoints = new Set(["voice_settings", "direct_voice_settings", "speech_server_settings", "realtime_asr_settings", "hotkeys"]
    .map(name => `/set/data/${name}`));

// These setters reply in FIFO order. Keep timed-out owners until their reply:
// a GET or a later write must never confirm an earlier, uncertain save.
export function createSettingsWriteResponses() {
    const queues = new Map();
    const begin = endpoint => {
        if (!endpoints.has(endpoint)) return null;
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
