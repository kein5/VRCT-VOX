import assert from "node:assert/strict";
import { test } from "node:test";
import { newerRoute, newerDirectState } from "./routeState.js";

const muted = { observation_id: "100", generation: 4, requested_muted: true, observed_muted: true, pending: false, ready: true };
const resuming = { ...muted, observation_id: "101", generation: 5, requested_muted: false, pending: true };
const open = { ...resuming, observation_id: "102", observed_muted: false, pending: false };

test("late confirmed mute cannot overwrite a resume or open state", () => {
    assert.equal(newerRoute(resuming, muted), resuming);
    assert.equal(newerRoute(open, muted), open);
});
test("observations within the same generation cannot roll back confirmation", () => {
    assert.equal(newerRoute(open, resuming), open);
    assert.equal(newerRoute(resuming, open), open);
});
test("a restarted backend can advance despite resetting its generation", () => {
    const restarted = { ...muted, observation_id: "200", generation: 0 };
    assert.equal(newerRoute(open, restarted), restarted);
    assert.equal(newerRoute(restarted, open), restarted);
});
test("missing or invalid ordering data cannot assert mute", () => {
    assert.equal(newerRoute(open, { ...muted, observation_id: undefined }), open);
    assert.equal(newerRoute(open, { ...muted, observation_id: "invalid" }), open);
    assert.equal(newerRoute({}, muted), muted);
});
test("a newer direct state keeps the previous settings object when they are unchanged", () => {
    const first = { observation_id: "1", requested: false, settings: { mode: "converted", rvc_model: "a.pth" } };
    const same = newerDirectState(first, { observation_id: "2", requested: false, settings: { mode: "converted", rvc_model: "a.pth" } });
    assert.equal(same.observation_id, "2");
    assert.equal(same.settings, first.settings);
    const changed = newerDirectState(same, { observation_id: "3", settings: { mode: "converted", rvc_model: "b.pth" } });
    assert.deepEqual(changed.settings, { mode: "converted", rvc_model: "b.pth" });
    assert.notEqual(changed.settings, first.settings);
    assert.equal(newerDirectState(changed, { ...first, observation_id: "2" }), changed); // 古い観測は捨てる
    assert.deepEqual(newerDirectState({}, first), first);
});
