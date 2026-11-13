import * as routeState from "./routeState.js";
import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, stubGlobals, eventTarget, find } from "../test/hookHarness.js";
import { flush } from "../test/bridgeHarness.js";
import { rebaseDraft } from "./draftRebase.js";
import { changedPaths } from "./saveBar.js";
import { createSettingsWriteResponses } from "../common/settingsWriteResponses.js";

async function setup(context) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtimes = [];
    context.after(() => runtimes.forEach(runtime => runtime.unmount()));
    stubGlobals(context, { window: eventTarget() });
    const owners = createSettingsWriteResponses(), requests = [], entries = [], forms = [];
    const state = { settings: { routing: "external", output_device: "output-a", monitor_volume: "35" }, error: null,
        directState: { observation_id: 1 }, devices: { devices: [] }, updateError: error => { state.error = error; },
        send: (endpoint, data) => {
            if (!endpoint.startsWith("/set/")) return true;
            const owner = owners.begin(endpoint);
            requests.push({ endpoint, data });
            return owner.response;
        },
    };
    for (const [index, file, name] of [[0, "device/VoiceRouteSettings.jsx", "VoiceRouteSettings"],
        [1, "advanced_settings/VoiceSettings.jsx", "TtsOutputDeviceSettings"]]) {
        const runtime = hooks();
        runtimes.push(runtime);
        const draft = await loadModule(new URL("./useSettingsDraft.jsx", import.meta.url), runtime, {
            "./draftRebase": { rebaseDraft }, "./saveBar": { changedPaths, setSaveBarEntry: (_, value) => { entries[index] = value; } },
        });
        const components = await loadModule(new URL(`../../views/app/config_page/setting_section/setting_box/${file}`, import.meta.url), runtime, {
            "@store": {}, "../../../../../../logics/voice/useVoice": { useVoice: () => state },
            "../../../../../../logics/voice/routeState": routeState,
            "../../../../../../logics/voice/useSettingsDraft": draft,
            "../tts/GenerationOptions": { validGenerationOptions: () => true }, "../device/VoiceRouteSettings": {},
            "./StatusLine": {}, "../_components/description/Description": {},
            "../_components/section_label_component/SectionLabelComponent": { SectionLabelComponent: "heading" },
            "../_components/env_readout/EnvReadout": {}, "../_components/form_row/FormRow": { FormRow: "row" },
        });
        forms.push(() => runtime.render(components[name], { title: "Output" }));
    }
    context.after(() => owners.stop());
    const render = () => { forms.forEach(form => form()); return forms.map(form => form()); };
    const edit = (index, value) => { find(render()[index], node => node.type === "select").props.onChange({ target: { value } }); render(); };
    const reply = async (index, status) => {
        const request = requests[index];
        if (status === 200) state.settings = { ...state.settings, ...request.data };
        render();
        owners.receive({ endpoint: request.endpoint, status, result: status === 200 ? state.settings : { error_code: "rejected" } });
        await flush(); render();
    };
    render();
    return { entries, requests, state, edit, render, reply };
}

for (const reverse of [false, true]) test(`VRChat forms save only their edits and own their responses (reverse=${reverse})`, async context => {
    const s = await setup(context);
    s.edit(0, "managed"); s.edit(1, "output-b");
    const order = reverse ? [1, 0] : [0, 1];
    for (const index of order) s.entries[index].save();
    s.render();
    assert.deepEqual(s.requests.map(request => request.data), order.map(index => index ? { output_device: "output-b" } : { routing: "managed" }));
    await s.reply(0, 200);
    assert.equal(s.entries[order[0]].saving, false);
    assert.equal(s.entries[order[1]].saving, true, "another form's response cannot confirm this save");
    await s.reply(1, 200);
    assert.deepEqual(s.state.settings, { routing: "managed", output_device: "output-b", monitor_volume: "35" });
    assert.ok(s.entries.every(entry => !entry.dirty && entry.saveState === "saved"));
});

test("a rejected route edit stays dirty when the output form saves successfully", async context => {
    const s = await setup(context);
    s.edit(0, "managed"); s.edit(1, "output-b");
    s.entries.forEach(entry => entry.save()); s.render();
    await s.reply(0, 409); await s.reply(1, 200);
    assert.equal(s.state.settings.routing, "external");
    assert.equal(s.state.settings.output_device, "output-b");
    assert.equal(s.entries[0].dirty, true);
    assert.equal(s.entries[1].dirty, false);
    assert.equal(find(s.render()[0], node => node.type === "select").props.value, "managed");
});
