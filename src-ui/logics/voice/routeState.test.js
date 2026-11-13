import assert from "node:assert/strict";
import { test } from "node:test";
import { directRouteReady, newerRoute, newerDirectState, usesOutputDevice } from "./routeState.js";

const muted = { observation_id: "100", generation: 4, requested_muted: true, observed_muted: true, pending: false, ready: true };
const resuming = { ...muted, observation_id: "101", generation: 5, requested_muted: false, pending: true };
const open = { ...resuming, observation_id: "102", observed_muted: false, pending: false };

test("the managed route needs managed routing, and the device route an output device", () => {
    const managedRoute = { output_route: "managed" }, deviceRoute = { output_route: "device" };
    assert.equal(directRouteReady({ routing: "managed" }, managedRoute), true);
    assert.equal(directRouteReady({ routing: "external", output_device: "cable" }, managedRoute), false);
    assert.equal(directRouteReady({ routing: "external", output_device: "cable" }, deviceRoute), true);
    assert.equal(directRouteReady({ routing: "external", output_device: "" }, deviceRoute), false);
    assert.equal(directRouteReady(null, deviceRoute), false);
    assert.equal(usesOutputDevice({}), false);
});
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
    assert.equal(same, first);
    assert.equal(same.settings, first.settings);
    const changed = newerDirectState(same, { observation_id: "3", settings: { mode: "converted", rvc_model: "b.pth" } });
    assert.deepEqual(changed.settings, { mode: "converted", rvc_model: "b.pth" });
    assert.notEqual(changed.settings, first.settings);
    assert.equal(newerDirectState(changed, { ...first, observation_id: "2" }), changed);
    assert.deepEqual(newerDirectState({}, first), first);
});

test("changed direct status keeps settings, while nested changes and generations publish", () => {
    const first = { observation_id: "1", generation: 1, requested: false, settings: { engine: "rvc", options: [1, 2] } };
    const changed = newerDirectState(first, { ...first, observation_id: "2", requested: true,
        settings: { options: [1, 2], engine: "rvc" } });
    assert.notEqual(changed, first);
    assert.equal(changed.settings, first.settings);
    assert.notEqual(newerRoute(first, { ...first, observation_id: "3", generation: 2 }), first);
    assert.notEqual(newerRoute(first, { ...first, observation_id: "4", settings: { engine: "rvc", options: [2, 1] } }), first);
    assert.notEqual(newerRoute(first, { ...first, observation_id: "5", error: null }), first);
});
