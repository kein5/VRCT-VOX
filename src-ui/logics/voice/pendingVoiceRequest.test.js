import assert from "node:assert/strict";
import { test } from "node:test";
import { pendingAfterVoiceFailure, stoppedVoiceStatus, stoppedDirectState } from "./pendingVoiceRequest.js";

for (const [endpoint, intent] of [["/run/enable_tts", true], ["/run/disable_tts", false],
    ["/run/start_direct_voice", true], ["/run/stop_direct_voice", false]]) {
    test(`terminal failure releases matching ${endpoint}, preserves newer opposite intent`, () => {
        assert.equal(pendingAfterVoiceFailure({ intent, generation: 4 }, endpoint), null);
        const newer = { intent: !intent, generation: 5 };
        assert.equal(pendingAfterVoiceFailure(newer, endpoint), newer);
    });
}

test("poll failures and unconfirmed timeout do not release an outstanding command", () => {
    const waiting = { intent: false, generation: 9 };
    for (const endpoint of [undefined, "/get/data/voice_status", "/get/data/direct_voice_state"])
        assert.equal(pendingAfterVoiceFailure(waiting, endpoint), waiting);
});

test("process exit clears busy flags without resetting generation or saved settings", () => {
    const status = { tts_enabled: true, tts_generation: 8, observation_id: "42", tts_stopping: true, tts_server_starting: true };
    assert.deepEqual(stoppedVoiceStatus(status), { ...status, tts_stopping: false, tts_server_starting: false });
    const direct = { generation: 5, observation_id: "40", settings: { engine: "rvc" }, requested: true, pending: true, stopping: true };
    assert.deepEqual(stoppedDirectState(direct), { ...direct, requested: false, pending: false, stopping: false });
});
