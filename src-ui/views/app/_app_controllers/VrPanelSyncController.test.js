import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../../../logics/test/hookHarness.js";
import * as wire from "../../../logics/common/vrPanelWire.js";

async function setup(context) {
    const runtime = hooks(), lifecycle = hooks(), listeners = new Map();
    const state = { enabled: true, configOpen: false, mic: true };
    const actions = [], requests = [], windows = [];
    let memory = { translation: false, transcription_send: false, transcription_receive: false };
    const common = {
        useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: state.configOpen },
            setIsOpenedConfigPage: value => { state.configOpen = value; } }),
        useVolume: () => ({ currentMicThresholdCheckStatus: { data: false }, currentSpeakerThresholdCheckStatus: { data: false } }),
    };
    const { VrPanelSyncController } = await loadModule(new URL("./VrPanelSyncController.jsx", import.meta.url), runtime, {
        "@tauri-apps/api/core": { invoke: async (name, args) => windows.push(args.open) },
        "@tauri-apps/api/event": { emit: async () => {}, listen: (name, handler) => {
            listeners.set(name, handler);
            return Promise.resolve(() => { if (listeners.get(name) === handler) listeners.delete(name); });
        } },
        jotai: { getDefaultStore: () => ({}) }, "@store": { dynamicStoreRegistry: {} },
        "@logics_common": common,
        "@logics_configs": { useVr: () => ({ currentIsEnabledOverlayVrPanel: { data: state.enabled } }) },
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: async (...args) => requests.push(args) }) },
        "../../../logics/common/vrPanelWire": wire,
        "../../../logics/main/languageMutations": { isLanguageMutation: () => false, rejectLanguageMutation: () => {} },
    });
    const { ConfigPageCloseTriggerController } = await loadModule(new URL("./ConfigPageCloseTriggerController.jsx", import.meta.url), lifecycle, {
        "@logics_common": common,
        "@store": { useStore_MainFunctionsStateMemory: () => ({ currentMainFunctionsStateMemory: { data: memory },
            updateMainFunctionsStateMemory: value => { memory = value; } }) },
        "@logics_main": { useMainFunction: () => ({
            currentTranslationStatus: { data: false }, currentTranscriptionReceiveStatus: { data: false },
            currentTranscriptionSendStatus: { data: state.mic },
            setTranscriptionSend: (value, options) => { actions.push([value, options]); state.mic = value; },
            pendingTranscriptionSendStatus: () => {},
        }) },
    });
    context.after(() => { runtime.unmount(); lifecycle.unmount(); });
    const render = () => { runtime.render(VrPanelSyncController); lifecycle.render(ConfigPageCloseTriggerController); };
    const config = value => { listeners.get("vr-panel-config-page")({ payload: value }); render(); };
    render();
    return { state, actions, requests, windows, listeners, runtime, render, config };
}

test("recreating the VR panel leaves settings open and microphone paused", async context => {
    const view = await setup(context);
    view.config(true);
    assert.equal(view.state.mic, false);
    view.state.enabled = false;
    view.render();
    await Promise.resolve();
    view.state.enabled = true;
    view.render();
    view.config(false); // The new panel starts with no popup.
    assert.equal(view.state.configOpen, true);
    assert.equal(view.state.mic, false);
    assert.deepEqual(view.actions, [[false, { reason: "settings_pause" }]]);
    assert.deepEqual(view.windows, [true, false, true]);
    view.listeners.get("vr-panel-stdout")({ payload: { path: "/set/enable/transcription_send" } });
    assert.deepEqual(view.requests, []); // The old panel no longer owns the pause.
});

for (const dispose of ["disable", "unmount"]) {
    test(`late callbacks after ${dispose} cannot reacquire settings ownership`, async context => {
        const view = await setup(context);
        view.config(true);
        const oldConfig = view.listeners.get("vr-panel-config-page");
        const oldStdout = view.listeners.get("vr-panel-stdout");
        if (dispose === "disable") {
            view.state.enabled = false;
            view.render();
        } else view.runtime.unmount();
        // Unlisten is asynchronous; callbacks may already be queued.
        oldConfig({ payload: false });
        view.state.configOpen = false;
        oldConfig({ payload: true });
        assert.equal(view.state.configOpen, false);
        oldStdout({ payload: { path: "/set/enable/transcription_send" } });
        assert.deepEqual(view.requests, []);
        assert.equal(view.state.mic, false);
    });
}

test("a live panel closes its own settings and restores the microphone", async context => {
    const view = await setup(context);
    view.config(true);
    view.config(false);
    assert.equal(view.state.configOpen, false);
    assert.equal(view.state.mic, true);
    assert.deepEqual(view.actions, [[false, { reason: "settings_pause" }], [true, undefined]]);
});

test("a live panel cannot close settings first opened on the desktop", async context => {
    const view = await setup(context);
    view.state.configOpen = true;
    view.render();
    view.config(true);
    view.config(false);
    assert.equal(view.state.configOpen, true);
    assert.equal(view.state.mic, false);
});
