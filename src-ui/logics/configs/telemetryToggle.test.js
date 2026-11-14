import assert from "node:assert/strict";
import { test } from "node:test";
import { toggleTelemetryOrAnswer } from "./telemetryToggle.js";

const switchWith = (enabled, pending) => {
    const calls = [];
    return { calls, others: {
        currentTelemetry: { data: enabled }, currentTelemetryNotice: { data: { pending, enabled } },
        toggleTelemetry: () => calls.push(["toggle"]),
        setTelemetryNotice: answer => { calls.push(["answer", answer]); return Promise.resolve(); },
        getTelemetry: () => calls.push(["read"]),
    } };
};

// SEC-07: /set/enable/telemetry is no answer to the notice; the settings page answers it itself.
test("turning it on while the notice is unanswered answers the notice", async () => {
    const { calls, others } = switchWith(false, true);
    await toggleTelemetryOrAnswer(others);
    assert.deepEqual(calls, [["answer", { send: true }], ["read"]]);
});

test("turning it off, or switching after the notice was answered, uses the switch", async () => {
    for (const [enabled, pending] of [[true, true], [true, false], [false, false]]) {
        const { calls, others } = switchWith(enabled, pending);
        await toggleTelemetryOrAnswer(others);
        assert.deepEqual(calls, [["toggle"]], `enabled=${enabled} pending=${pending}`);
    }
});
