import assert from "node:assert/strict";
import { test } from "node:test";
import { createStore } from "jotai/vanilla";
import { hooks, loadModule } from "../test/hookHarness.js";
import * as polledState from "../common/polledState.js";
import * as routeState from "./routeState.js";
import * as pendingVoiceRequest from "./pendingVoiceRequest.js";

async function setup(file, name) {
    const runtime = hooks();
    const module = await loadModule(new URL(file, import.meta.url), runtime, {
        "../common/polledState.js": polledState, "./routeState": routeState,
        "./pendingVoiceRequest.js": pendingVoiceRequest,
    });
    const render = () => runtime.render(module[name]);
    return { runtime, render, useHook: module[name] };
}
const clone = value => JSON.parse(JSON.stringify(value));
const observe = (runtime, value) => {
    const target = runtime.targets.find(target => runtime.store.get(target) === value);
    assert.ok(target);
    let changes = 0;
    const unsubscribe = runtime.store.sub(target, () => changes++);
    return { target, get changes() { return changes; }, unsubscribe };
};

for (const [field, update, first, change] of [
    ["status", "updateStatus", { tts_generation: 2, tts_enabled: true, engines: ["one"] }, { tts_enabled: false }],
    ["route", "updateRoute", { generation: 2, requested_muted: false, observed_muted: false }, { requested_muted: true }],
    ["directState", "updateDirectState", { generation: 2, requested: true, mode: "converted", settings: { engine: "rvc" } }, { requested: false }],
]) test(`${field}: equal polls do not notify; an overtaken response cannot roll back state`, async () => {
    const { runtime, render } = await setup("./useVoice.js", "useVoice");
    render()[update]({ ...first, observation_id: "100" });
    const before = render()[field], subscription = observe(runtime, before);
    // The cursor advances even though the rendered state keeps its old ID.
    render()[update]({ ...clone(first), observation_id: "103" });
    render()[update]({ ...clone(first), ...change, observation_id: "102" });
    assert.equal(render()[field], before);
    assert.equal(subscription.changes, 0);
    render()[update]({ ...clone(first), ...change, observation_id: "104" });
    assert.notEqual(render()[field], before);
    assert.equal(subscription.changes, 1);
    const changed = render()[field];
    render()[update]({ ...clone(first), observation_id: "104" });
    for (const observation_id of [undefined, "bad", "-1"]) render()[update]({ ...first, observation_id });
    assert.equal(render()[field], changed);
    render().backendStopped();
    const stopped = render()[field];
    render()[update]({ ...first, observation_id: "103" });
    assert.equal(render()[field], stopped);
    render().reset();
    render()[update]({ ...first, observation_id: "1" });
    assert.equal(render()[field].observation_id, "1");
    subscription.unsubscribe();
});

test("separate voice hook instances share ordering before another render", async () => {
    const { runtime, useHook } = await setup("./useVoice.js", "useVoice");
    const render = () => runtime.render(() => [useHook(), useHook()]);
    const [first, second] = render();
    first.updateRoute({ observation_id: "100", observed_muted: false });
    const before = render()[0].route;
    second.updateRoute({ observation_id: "103", observed_muted: false });
    first.updateRoute({ observation_id: "102", observed_muted: true });
    assert.equal(render()[0].route, before);
    assert.equal(render()[1].route, before);
});

test("observation cursors are isolated by store and atom", async () => {
    const { runtime, render } = await setup("./useVoice.js", "useVoice");
    const firstStore = runtime.store;
    const first = { observation_id: "100", tts_generation: 1, tts_enabled: true };
    render().updateStatus(first);
    render().updateStatus({ ...first, observation_id: "200" });
    render().updateRoute({ observation_id: "2", ready: true });
    assert.equal(render().route.ready, true);
    runtime.store = createStore();
    render().updateStatus({ ...first, observation_id: "1", tts_enabled: false });
    assert.equal(render().status.tts_enabled, false);
    runtime.store = firstStore;
    render().updateStatus({ ...first, observation_id: "150", tts_enabled: false });
    assert.equal(render().status, first);
});

for (const [field, update, pending, error, command, first, acknowledged] of [
    ["status", "updateStatus", "ttsPending", "ttsError", "/run/enable_tts",
        { tts_generation: 3, tts_enabled: false }, { tts_generation: 4, tts_enabled: true }],
    ["directState", "updateDirectState", "directPending", "directError", "/run/start_direct_voice",
        { generation: 3, requested: false, mode: "off" }, { generation: 4, requested: true, mode: "converted", settings: { engine: "rvc" } }],
]) test(`${pending}: acknowledgement runs even when the accepted snapshot keeps its reference`, async t => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { runtime, render } = await setup("./useVoice.js", "useVoice");
    render()[update]({ ...first, observation_id: "100" });
    await render().send(command, { mode: "converted", options: { engine: "rvc" } });
    const request = render()[pending], pendingTarget = observe(runtime, request).target;
    t.mock.timers.tick(5000);
    assert.equal(render()[error], "voice_request_unconfirmed");
    render()[update]({ ...acknowledged, observation_id: "102" });
    assert.equal(render()[pending], null);
    assert.equal(render()[error], null);
    const before = render()[field], subscription = observe(runtime, before);
    // Recreate an outstanding acknowledgement independently of rendered state.
    runtime.store.set(pendingTarget, request);
    render()[update]({ ...clone(acknowledged), observation_id: "104" });
    assert.equal(render()[pending], null);
    assert.equal(render()[field], before);
    assert.equal(subscription.changes, 0);
    runtime.store.set(pendingTarget, request);
    render()[update]({ ...acknowledged, observation_id: "103" });
    assert.equal(render()[pending], request);
    subscription.unsubscribe();
});

test("TTS generation guard and direct stop/error acknowledgement conditions remain intact", async t => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const { render } = await setup("./useVoice.js", "useVoice");
    render().updateStatus({ observation_id: "1", tts_generation: 5, tts_enabled: true });
    const status = render().status;
    render().updateStatus({ observation_id: "2", tts_generation: 4, tts_enabled: false });
    assert.equal(render().status, status);
    render().updateDirectState({ observation_id: "1", generation: 5, requested: true });
    await render().send("/run/stop_direct_voice");
    render().updateDirectState({ observation_id: "2", generation: 6, requested: false, stopping: true });
    assert.ok(render().directPending);
    render().updateDirectState({ observation_id: "3", generation: 6, requested: false, stopping: false });
    assert.equal(render().directPending, null);
    await render().send("/run/start_direct_voice", { mode: "converted" });
    render().updateDirectState({ observation_id: "4", generation: 7, requested: false, error: "failed" });
    assert.equal(render().directPending, null);
});

test("downloads and hardware skip equal observations, reject overtaken responses and reset their cursors", async () => {
    const { runtime, render } = await setup("./useModelDownloads.js", "useModelDownloads");
    for (const [field, update, first, changed] of [
        ["state", "updateState", { jobs: { model: { phase: "downloading", bytes: 10 } } }, { jobs: { model: { phase: "downloading", bytes: 20 } } }],
        ["hardware", "updateHardware", { phase: "ready", devices: [{ name: "gpu", memory: 8 }] }, { phase: "failed", devices: [] }],
    ]) {
        render()[update]({ ...first, observation_id: "100" });
        const before = render()[field], subscription = observe(runtime, before);
        render()[update]({ ...clone(first), observation_id: "103" });
        render()[update]({ ...changed, observation_id: "102" });
        assert.equal(render()[field], before);
        assert.equal(subscription.changes, 0);
        render()[update]({ ...changed, observation_id: "104" });
        assert.notEqual(render()[field], before);
        render().reset();
        render()[update]({ ...first, observation_id: "1" });
        assert.equal(render()[field].observation_id, "1");
        subscription.unsubscribe();
    }
    const snapshot = { observation_id: "5", jobs: {} };
    assert.equal(render().updateState(snapshot), true);
    const before = render().state;
    assert.equal(render().updateState({ ...snapshot, observation_id: "8" }), true);
    assert.equal(render().state, before);
    await render().send("/run/start_model_download", { id: "model" });
    assert.ok(render().pending);
    render().acknowledge({ observation_id: "7", jobs: { model: { phase: "queued" } } });
    assert.equal(render().pending, null);
    assert.equal(render().state, before);
});

test("speech servers preserve rows and pending objects while retaining generation/phase guards", async () => {
    const { runtime, render } = await setup("./useSpeechServers.js", "useSpeechServers");
    const first = { japanese: { generation: 2, state: "ready", base_url: "local" }, asr: { generation: 1, state: "stopped" } };
    render().updateState(first);
    const state = render().state, pending = render().pending, subscription = observe(runtime, state);
    render().updateState(clone(first));
    assert.equal(render().state, state);
    assert.equal(render().pending, pending);
    assert.equal(subscription.changes, 0);
    render().updateState({ japanese: { ...first.japanese, base_url: "changed" } });
    assert.notEqual(render().state, state);
    assert.equal(render().state.asr, state.asr);
    await render().send("/run/stop_speech_server", { profile: "japanese" });
    const request = render().pending, target = observe(runtime, request).target;
    const stopped = { japanese: { generation: 3, state: "stopped", base_url: null } };
    render().updateState(stopped);
    assert.deepEqual(render().pending, {});
    const confirmed = render().state;
    runtime.store.set(target, request);
    render().updateState(clone(stopped));
    assert.deepEqual(render().pending, {});
    assert.equal(render().state, confirmed);
    render().updateState(first);
    assert.equal(render().state, confirmed);
    render().updateState({ japanese: { generation: 3, state: "ready" } });
    const ready = render().state;
    render().updateState({ japanese: { generation: 3, state: "preparing" } });
    assert.equal(render().state, ready);
    subscription.unsubscribe();
});
