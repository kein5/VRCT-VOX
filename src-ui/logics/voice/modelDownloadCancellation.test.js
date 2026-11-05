import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../test/hookHarness.js";
import { loadBridgeRoutes } from "../test/bridgeHarness.js";
import * as polledState from "../common/polledState.js";

const apply = "/run/apply_model_download", cancel = "/run/cancel_model_download";
const request = { id: "model", job_id: "job" };

async function setup(t, transport = async () => true) {
    const runtime = hooks(), calls = [];
    const { useModelDownloads } = await loadModule(new URL("./useModelDownloads.js", import.meta.url), runtime, {
        "../common/polledState.js": polledState,
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: (...args) => {
            calls.push(args); return transport(...args);
        } }) },
    });
    const render = () => runtime.render(useModelDownloads);
    t.after(() => runtime.unmount());
    return { runtime, render, calls };
}

for (const first of [apply, cancel]) for (const failed of [false, true]) {
    test(`Apply and Cancel retain the other pending request after ${first} ${failed ? "fails" : "succeeds"}`, async t => {
        const s = await setup(t);
        await s.render().send(apply, request);
        await s.render().send(cancel, request);
        assert.equal(s.calls.length, 2);
        s.render().updateState({ observation_id: "20", jobs: { model: { ...request, phase: "cancelled" } } });
        if (failed) s.render().updateError("download_cancelled", first);
        else s.render().acknowledge({ observation_id: "19", jobs: {} }, first);
        assert.ok(s.render().pending, "the other operation is still pending");
        assert.equal(s.render().state.observation_id, "20");
        await s.render().send(apply, { id: "other", job_id: "other-job" });
        await s.render().send("/run/start_model_download", { id: "other" });
        assert.equal(s.calls.length, 2, "competing actions stay blocked");
        s.render().acknowledge({ observation_id: "21", jobs: {} }, first === apply ? cancel : apply);
        assert.equal(s.render().pending, null);
    });
}

test("only the matching job can cancel pending Apply; polls, errors and timeouts cannot release it", async t => {
    const s = await setup(t);
    await s.render().send(apply, request);
    await s.render().send(cancel, { ...request, job_id: "old-job" });
    await s.render().send(cancel, { ...request, id: "other" });
    assert.equal(s.calls.length, 1);
    s.render().updateError("download_failed", "/get/data/model_download_state");
    s.render().updateError("request_unconfirmed");
    assert.ok(s.render().pending);
    await s.render().send(cancel, request);
    await s.render().send(cancel, request);
    assert.equal(s.calls.length, 2, "duplicate Cancel is blocked");
    s.render().backendStopped();
    assert.equal(s.render().pending, null);
});

test("a failed Cancel write retains pending Apply", async t => {
    const s = await setup(t, async endpoint => endpoint !== cancel);
    await s.render().send(apply, request);
    await s.render().send(cancel, request);
    assert.ok(s.render().pending);
    s.render().acknowledge({ observation_id: "1", jobs: {} }, apply);
    assert.equal(s.render().pending, null);
});

test("the receive router correlates Apply and Cancel acknowledgements", async t => {
    const s = await setup(t);
    const bridge = await loadBridgeRoutes(undefined, null, { useModelDownloads: s.render });
    t.after(() => bridge.runtime.unmount());
    await s.render().send(apply, request);
    await s.render().send(cancel, request);
    bridge.receiveRoutes({ status: 200, endpoint: cancel, result: { observation_id: "1", jobs: {} } });
    assert.ok(s.render().pending);
    bridge.receiveRoutes({ status: 200, endpoint: apply, result: { observation_id: "2", jobs: {} } });
    assert.equal(s.render().pending, null);
});

test("the production model card enables matching Cancel during Apply verification", async t => {
    const s = await setup(t), ui = hooks();
    t.after(() => ui.unmount());
    const { ModelDownloads } = await loadModule(new URL("../../views/app/config_page/setting_section/setting_box/advanced_settings/ModelDownloads.jsx", import.meta.url), ui, {
        "@tauri-apps/api/core": { isTauri: () => false },
        "@tauri-apps/plugin-opener": {},
        "../../../../../../logics/voice/useModelDownloads": { useModelDownloads: s.render },
        "../../../../../../logics/voice/modelHardwareAdvice": { modelAdvice: () => ({}) },
        "../../../../../../logics/common/useConsentDialog": { useConsentDialog: () => ({ dialog: { current: null } }) },
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
    });
    s.render().updateCatalog({ models: [{ id: "model", target: "rvc", name: "Model", total_bytes: 10 }] });
    s.render().updateState({ observation_id: "1", jobs: { model: { job_id: "job", phase: "ready" } } });
    const render = () => ui.render(ModelDownloads, { targets: ["rvc"], expected: { rvc: {} } });
    const button = name => find(render(), node => node.type === "button" && node.props.children === `model_downloads.${name}`);
    button("apply").props.onClick();
    s.render().updateState({ observation_id: "2", jobs: { model: { job_id: "job", phase: "verifying" } } });
    assert.equal(button("cancel").props.disabled, false);
    assert.equal(button("review").props.disabled, true);
    button("cancel").props.onClick();
    assert.equal(button("cancel").props.disabled, true);
    assert.deepEqual(s.calls.filter(([endpoint]) => endpoint.startsWith("/run/")), [
        [apply, { ...request, expected: {} }], [cancel, request],
    ]);
});
