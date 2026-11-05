import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals } from "../../../../../../logics/test/hookHarness.js";
import { rebaseDraft } from "../../../../../../logics/voice/draftRebase.js";

async function fixture(context) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), barRuntime = hooks(), calls = [], listeners = [], responses = [];
    const window = {
        addEventListener(type, fn, options) { listeners.push({ type, fn, capture: !!options?.capture }); },
        removeEventListener(type, fn) { const i = listeners.findIndex(row => row.type === type && row.fn === fn); if (i >= 0) listeners.splice(i, 1); },
        dispatch(type, event) { [...listeners].sort((a, b) => Number(b.capture) - Number(a.capture))
            .filter(row => row.type === type).forEach(row => row.fn(event)); },
    };
    stubGlobals(context, { window });
    runtime.api.useSyncExternalStore = (_, snapshot) => snapshot();
    const saveBar = await loadModule(new URL("../../../../../../logics/voice/saveBar.js", import.meta.url), runtime);
    const draftHooks = await loadModule(new URL("../../../../../../logics/voice/useSettingsDraft.jsx", import.meta.url), runtime, {
        "./draftRebase": { rebaseDraft }, "./saveBar": saveBar,
    });
    const asr = {
        settings: { server: "external", base_url: "http://localhost:8080", model: "asr-model",
            mic: { endpoint: null, follow_default: true, language: "ja" },
            speaker: { endpoint: null, follow_default: true, language: "ja" },
            vocabulary: { builtin: true, terms: [] } },
        state: {}, endpoints: {}, models: {}, error: null,
        send: (endpoint, data) => {
            calls.push([endpoint, data]);
            if (endpoint.startsWith("/set/")) return new Promise(resolve => responses.push(resolve));
            return true;
        },
        updateError: error => { asr.error = error; },
    };
    const speech = { state: {}, send: () => {} };
    const { RealtimeASRSettings } = await loadModule(new URL("./RealtimeASRSettings.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t: key => key, i18n: { language: "ja" } }) },
        "../../../../../../logics/common/languageNames.js": { createLanguageNames: () => ({ fromCode: code => code }) },
        "../../../../../../logics/transcription/useRealtimeASR": { useRealtimeASR: () => asr },
        "../../../../../../logics/voice/useSpeechServers": { useSpeechServers: () => speech },
        "../../../../../../logics/voice/useSettingsDraft": draftHooks,
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
        "../_components/description/Description": { Description: "description" },
    });
    const { SaveBar } = await loadModule(new URL("../../../topbar/Topbar.jsx", import.meta.url), barRuntime, {
        "@logics_common": {}, "../../../../logics/voice/saveBar": saveBar, "../../../../logics/voice/useVoice": {},
    });
    let dialogProps;
    const modal = { open: false, showModal() { this.open = true; }, close() { this.open = false; dialogProps.onClose(); } };
    const bar = () => barRuntime.render(SaveBar, {}, tree => {
        const dialog = find(tree, node => node.type === "dialog");
        if (dialog) { dialog.ref.current = modal; dialogProps = dialog.props; }
    });
    const render = () => { runtime.render(RealtimeASRSettings); return runtime.render(RealtimeASRSettings); };
    const field = label => find(render(), node => node.type === "input" && node.props["aria-label"] === label).props;
    const entries = () => saveBar.useSaveBarEntries();
    const status = () => find(bar(), node => node.props?.role === "status").props.children;
    const changeURL = () => { field("realtime.url").onChange({ target: { value: "http://localhost:9090" } }); render(); };
    const writes = () => calls.filter(([endpoint]) => endpoint.startsWith("/set/"));
    const acknowledge = async value => {
        asr.settings = value;
        responses.shift()({ status: 200, result: value });
        for (let i = 0; i < 10; i++) await Promise.resolve();
        render();
    };
    context.after(() => { runtime.unmount(); barRuntime.unmount(); });
    render();
    return { runtime, barRuntime, asr, render, bar, field, entries, status, changeURL, writes, acknowledge, window, modal, listeners };
}

test("realtime drafts register and unregister with the shared save bar, including dictionary edits", async context => {
    const s = await fixture(context);
    assert.equal(s.entries().length, 1);
    assert.equal(s.status(), "voice_ui.saved");
    s.changeURL();
    let tree = s.render();
    find(tree, node => node.type === "input" && node.props.maxLength === 320).props.onChange({ target: { value: "VRChat=ブイアールチャット" } });
    tree = s.render();
    find(tree, node => node.type === "button" && node.props.children === "realtime.vocabulary_add").props.onClick();
    tree = s.render();
    assert.equal(tree.props["data-unsaved"], true);
    assert.deepEqual(s.entries()[0].changes, ["realtime.url", "realtime.vocabulary_user"]);
    assert.equal(s.status(), "voice_ui.unsaved");
    assert.deepEqual(s.writes(), [], "editing never submits");
    s.runtime.unmount();
    assert.deepEqual(s.entries(), []);
    s.barRuntime.unmount();
    assert.equal(s.listeners.length, 0);
});

test("the shared leave guard blocks category navigation until discard; keep editing preserves the draft", async context => {
    const s = await fixture(context);
    s.changeURL(); s.bar();
    let proceeded = 0;
    const leave = () => {
        const event = { defaultPrevented: false, detail: { proceed: () => proceeded++ },
            preventDefault() { this.defaultPrevented = true; } };
        s.window.dispatch("vrct:settings-leave", event);
        assert.equal(event.defaultPrevented, true);
        assert.equal(proceeded, 0);
        return s.bar();
    };
    let tree = leave();
    assert.equal(s.modal.open, true);
    assert.equal(find(s.render(), node => node.type === "dialog"), null, "capture guard owns the one leave dialog");
    find(tree, node => node.type === "button" && node.props.children === "voice_ui.keep_editing").props.onClick();
    assert.equal(s.modal.open, false);
    assert.equal(s.field("realtime.url").value, "http://localhost:9090");
    tree = leave();
    find(tree, node => node.type === "button" && node.props.children === "voice_ui.discard_leave").props.onClick();
    assert.equal(proceeded, 1);
    assert.equal(s.field("realtime.url").value, "http://localhost:8080");
    s.render();
    assert.equal(s.status(), "voice_ui.saved");
    assert.deepEqual(s.writes(), []);
});

for (const method of ["submit", "save bar"]) {
    test(`${method} waits for acknowledgement and publishes saving/saved without starting audio`, async context => {
        const s = await fixture(context);
        s.changeURL();
        if (method === "submit") {
            find(s.render(), node => node.type === "form").props.onSubmit({ preventDefault() {} });
        } else s.entries()[0].save();
        s.render();
        assert.equal(s.status(), "voice_ui.saving");
        assert.equal(s.field("realtime.url").readOnly, true);
        assert.equal(find(s.render(), node => node.type === "button" && node.props.type === "submit").props.disabled, true);
        find(s.render(), node => node.type === "form").props.onSubmit({ preventDefault() {} });
        assert.equal(s.writes().length, 1);
        assert.equal(s.writes()[0][0], "/set/data/realtime_asr_settings");
        assert.equal(s.writes()[0][1].base_url, "http://localhost:9090");
        await s.acknowledge(s.writes()[0][1]);
        assert.equal(s.status(), "voice_ui.saved");
        assert.equal(s.entries()[0].dirty, false);
    });
}

test("canonical vocabulary acknowledgement clears the save bar and enables realtime Start", async context => {
    const s = await fixture(context);
    s.asr.state = { mic: { requested: false }, speaker: { requested: false } };
    s.asr.models = { server: "external", configured_url: s.asr.settings.base_url, base_url: s.asr.settings.base_url,
        models: [{ id: "asr-model", languages: ["ja"] }] };
    find(s.render(), node => node.type === "input" && node.props.maxLength === 320).props.onChange({ target: { value: "VRChat = ブイアールチャット" } });
    find(s.render(), node => node.type === "button" && node.props.children === "realtime.vocabulary_add").props.onClick();
    s.render(); s.entries()[0].save(); s.render();
    const sent = s.writes()[0][1];
    await s.acknowledge({ ...sent, vocabulary: { ...sent.vocabulary, terms: ["VRChat=ブイアールチャット"] } });
    assert.equal(s.entries()[0].dirty, false);
    assert.equal(s.status(), "voice_ui.saved");
    assert.equal(find(s.render(), node => node.type === "button" && node.props.children === "realtime.start_mic").props.disabled, false);
    context.mock.timers.tick(5000); s.render();
    assert.equal(s.asr.error, null);
});

test("rejected and unconfirmed saves keep edits visible and guarded; refresh does not erase them", async context => {
    const s = await fixture(context);
    s.changeURL();
    s.asr.settings = { ...s.asr.settings, model: "refreshed-model" };
    s.render();
    assert.equal(s.field("realtime.url").value, "http://localhost:9090");
    s.entries()[0].save(); s.render();
    s.asr.error = "invalid_settings"; s.render();
    assert.equal(s.status(), "voice_ui.save_failed");
    assert.equal(s.entries()[0].edited, true);
    assert.equal(s.field("realtime.url").readOnly, false);
    s.entries()[0].save(); s.render();
    context.mock.timers.tick(5000);
    s.render();
    assert.equal(s.asr.error, "save_unconfirmed");
    assert.equal(s.status(), "voice_ui.save_failed");
    const event = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    s.window.dispatch("beforeunload", event);
    assert.equal(event.defaultPrevented, true);
    assert.equal(event.returnValue, "");
    s.entries()[0].discard(); s.render();
    assert.equal(s.status(), "voice_ui.saved");
});
