import * as routeState from "../../../../../../logics/voice/routeState.js";
import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../logics/test/hookHarness.js";

async function setup({ seed = "invalid", instructions = "\u0001", modelOptions = {} } = {}) {
    const runtime = hooks();
    const draft = { japanese_seed: seed, japanese_instructions: instructions, japanese_server: "external", japanese_url: "" };
    const { GenerationOptions, validGenerationOptions } = await loadModule(new URL("./GenerationOptions.jsx", import.meta.url), runtime, {
        "../../../../../../logics/voice/useVoice": { useVoice: () => ({ settings: draft, modelOptions, send: () => {} }) },
        "../../../../../../logics/voice/useSpeechServers": { useSpeechServers: () => ({ state: {} }) },
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
        "../_components/form_row/FormRow": { FormRow: "row" },
    });
    return { runtime, draft, GenerationOptions, validGenerationOptions,
        render: () => runtime.render(GenerationOptions, { role: "japanese", draft, field: () => {}, errorId: "options-error" }) };
}

test("invalid TTS seed and instruction point to the shared form error and clear after correction", async () => {
    const s = await setup();
    let tree = s.render();
    for (const type of ["input", "textarea"]) {
        const field = find(tree, node => node.type === type);
        assert.equal(field.props["aria-invalid"], true);
        assert.equal(field.props["aria-describedby"], "options-error");
    }
    assert.equal(s.validGenerationOptions(s.draft), false);
    s.draft.japanese_seed = "42"; s.draft.japanese_instructions = "話す速さをゆっくりに";
    tree = s.render();
    for (const type of ["input", "textarea"]) {
        const field = find(tree, node => node.type === type);
        assert.equal(field.props["aria-invalid"], false);
        assert.equal(field.props["aria-describedby"], undefined);
    }
    assert.equal(s.validGenerationOptions(s.draft), true);
    s.runtime.unmount();
});

test("TTS model-specific seed range error is associated without changing the save contract", async t => {
    t.mock.timers.enable({ apis: ["setInterval"] });
    const s = await setup({ seed: "123", instructions: "", modelOptions: { japanese: {
        server: "external", configured_url: "http://local", options: { seed: { minimum: 0, maximum: 100 } },
    } } });
    s.draft.japanese_url = "http://local";
    const tree = s.render(), input = find(tree, node => node.type === "input"), alert = find(tree, node => node.props?.role === "alert");
    assert.equal(input.props["aria-invalid"], true);
    assert.equal(input.props["aria-describedby"], alert.props.id);
    assert.equal(s.validGenerationOptions(s.draft), true); // Model support is advisory, as before.
    s.runtime.unmount();
});

test("TTS form supplies an existing error ID to both language groups", async () => {
    const s = await setup(), runtime = hooks();
    const { VoiceSettings } = await loadModule(new URL("../advanced_settings/VoiceSettings.jsx", import.meta.url), runtime, {
        "../../../../../../logics/voice/useVoice": { useVoice: () => ({ settings: s.draft, status: {}, devices: {}, send: () => {} }) },
        "../../../../../../logics/voice/useSettingsDraft": { useSettingsDraft: () => ({ draft: s.draft }) },
        "../tts/GenerationOptions": { GenerationOptions: s.GenerationOptions, validGenerationOptions: s.validGenerationOptions },
        "../device/VoiceRouteSettings": { VoiceRouteSummary: "route" },
        "../_components/section_label_component/SectionLabelComponent": { SectionLabelComponent: "heading" },
        "./StatusLine": { StatusLine: "status" },
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
        "../_components/description/Description": { Description: "description" },
        "../_components/form_row/FormRow": { FormRow: "row" },
    });
    const tree = runtime.render(VoiceSettings), alert = find(tree, node => node.props?.role === "alert");
    const groups = [];
    find(tree, node => { if (node.type === s.GenerationOptions) groups.push(node); return false; });
    assert.equal(groups.length, 2);
    for (const group of groups) assert.equal(group.props.errorId, alert.props.id);
    runtime.unmount(); s.runtime.unmount();
});

for (const [pitch, rate] of [[25, 0.5], [0, -1], [NaN, NaN]]) test(`RVC numeric fields reference their error (${pitch}, ${rate})`, async () => {
    const runtime = hooks();
    const draft = { mode: "converted", engine: "rvc", rvc_pitch: pitch, rvc_index_rate: rate,
        rvc_runtime: "", rvc_model: "", rvc_index: "" };
    const { DirectVoiceSettings } = await loadModule(new URL("../advanced_settings/DirectVoiceSettings.jsx", import.meta.url), runtime, {
        "../../../../../../logics/voice/useSettingsDraft": { useSettingsDraft: () => ({ draft }) },
        "../../../../../../logics/voice/routeState": routeState,
        "../../../../../../logics/voice/useVoice": { useVoice: () => ({ directState: { settings: draft }, directSources: {},
            settings: { routing: "managed" }, route: {}, send: () => {}, setDirectDraftBlocked: () => {} }), sourceKey: value => value },
        "../device/VoiceRouteSettings": { VoiceRouteSummary: "route", VoiceRouteControls: "controls" },
        "../_components/section_label_component/SectionLabelComponent": { SectionLabelComponent: "heading" },
        "./ModelDownloads": { ModelDownloads: "downloads" }, "./VcRuntimeSetup": { VcRuntimeSetup: "runtime" }, "./StatusLine": { StatusLine: "status" },
        "../_components/setup_section/SetupSection": { SetupSection: "setup" },
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
        "../_components/description/Description": { Description: "description" },
        "../_components/form_row/FormRow": { FormRow: "row" },
        "../_components/custom_model_link/CustomModelLink": { CustomModelLink: "custom-model-link" },
    });
    const tree = runtime.render(DirectVoiceSettings, { variant: "rvc" });
    const alert = find(tree, node => node.props?.children === "voice_ui.invalid_rvc_numbers");
    const fields = [];
    find(tree, node => { if (node.type === "input" && node.props.type === "number") fields.push(node); return false; });
    assert.equal(fields.length, 2);
    for (const field of fields) {
        assert.equal(field.props["aria-describedby"], alert.props.id);
        assert.equal(typeof field.props["aria-invalid"], "boolean");
    }
    assert.ok(fields.some(field => field.props["aria-invalid"]));
    runtime.unmount();
});
