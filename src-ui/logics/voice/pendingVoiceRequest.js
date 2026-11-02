const intents = {
    "/run/enable_tts": true, "/run/disable_tts": false,
    "/run/start_direct_voice": true, "/run/stop_direct_voice": false,
};

// An error for an older ON must not release a newer OFF (or vice versa).
// Poll errors and timeout notices are not terminal command responses.
export const pendingAfterVoiceFailure = (pending, endpoint) =>
    pending && Object.hasOwn(intents, endpoint) && pending.intent === intents[endpoint] ? null : pending;

export const stoppedVoiceStatus = value => ({ ...value, tts_stopping: false, tts_server_starting: false });
export const stoppedDirectState = value => ({ ...value, requested: false, pending: false, stopping: false });
