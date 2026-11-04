import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import yaml from "js-yaml";
import { hooks, loadModule, find } from "../test/hookHarness.js";

const noop = () => {};
const api = values => new Proxy(values, { get: (object, name) => object[name] ?? noop });

async function fixture(context) {
    const runtime = hooks(), calls = [];
    const consent = await loadModule(new URL("./useTranscriptionConsent.js", import.meta.url), runtime);
    const states = {};
    const mainStore = { store: {} };
    for (const name of ["Translation", "TranscriptionSend", "TranscriptionReceive", "OcrCapture", "Foreground"]) {
        states[name] = { data: false, state: "ok" };
        mainStore[`useStore_${name}Status`] = () => ({
            [`current${name}Status`]: states[name],
            [`pending${name}Status`]: () => { states[name].state = "pending"; },
            [`update${name}Status`]: (value, options) => {
                const data = typeof value === "function" ? value(states[name]) : value;
                states[name] = { data, state: options?.set_state ?? "ok" };
            },
        });
    }
    const main = await loadModule(new URL("../main/useMainFunction.js", import.meta.url), runtime, {
        "@store": mainStore,
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: async (...args) => { calls.push(args); return true; } }) },
    });
    const transcription = api({
        currentSelectedTranscriptionEngine: { data: null, state: "ok" },
        currentSelectableTranscriptionEngines: { data: ["Google", "Whisper"] },
        currentSelectedWhisperWeightType: { data: "base", state: "ok" },
        setSelectedTranscriptionEngine: async value => {
            transcription.currentSelectedTranscriptionEngine = { data: null, state: "pending" };
            calls.push(["/set/data/selected_transcription_engine", value]);
            return true;
        },
        pendingWhisperWeightTypeStatus: value => calls.push(["pending", value]),
        downloadWhisperWeightTypeStatus: value => calls.push(["/run/download_whisper_weight", value]),
    });
    const configs = { useTranscription: () => transcription };
    for (const name of ["Translation", "Others", "Ocr", "AdvancedSettings"]) configs[`use${name}`] = () => api({});
    const common = {};
    for (const name of ["NotificationStatus", "Volume", "LLMConnection", "IsSoftwareUpdating"]) common[`use${name}`] = () => api({});
    const errors = await loadModule(new URL("../_useBackendErrorHandling.js", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t: key => key, i18n: { exists: () => true } }) },
        "@logics_common": common, "@logics_configs": configs, "@logics_main": main,
        "./ui_configs": {}, "./configs/legacyModelConsent": {}, "./configs/cloudTranscription": { CLOUD_TRANSCRIPTION_ENGINES: [] },
        "./transcription/useTranscriptionConsent": consent,
    });
    const error = errors._useBackendErrorHandling().errorHandling_Backend;
    const { TranscriptionConsentController } = await loadModule(new URL("../../views/app/_app_controllers/TranscriptionConsentController.jsx", import.meta.url), runtime, {
        "@logics_configs": configs, "@logics_main": main,
        "@store": { useStore_IsOpenedConfigPage: () => ({ updateIsOpenedConfigPage: noop }),
            useStore_SelectedConfigTabId: () => ({ updateSelectedConfigTabId: noop }) },
        "../../../logics/transcription/useTranscriptionConsent": consent,
        "../../../logics/common/useConsentDialog": { useConsentDialog: () => ({ dialog: { current: null }, close: noop }) },
        "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog": { LegacyModelDownloadDialog: "download-consent" },
    });
    const render = () => runtime.render(TranscriptionConsentController);
    const click = key => find(render(), node => node.type === "button" && node.props.children === `transcription_consent.${key}`).props.onClick();
    const acknowledge = value => { transcription.currentSelectedTranscriptionEngine = { data: value, state: "ok" }; render(); };
    const firstEnable = direction => {
        main.useMainFunction()[`toggleTranscription${direction}`]();
        error({ error_code: "TRANSCRIPTION_ENGINE_NOT_SELECTED", endpoint: `/set/enable/transcription_${direction === "Send" ? "send" : "receive"}`, data: false });
        render();
    };
    context.after(() => runtime.unmount());
    render();
    return { runtime, render, calls, states, transcription, configs, click, acknowledge, firstEnable, error, consent };
}

for (const direction of ["Send", "Receive"]) test(`${direction}: first enable opens chooser; Google saves then continues only the original enable`, async context => {
    const s = await fixture(context);
    assert.equal(s.render(), null);
    s.firstEnable(direction);
    assert.ok(find(s.render(), node => node.type === "dialog"));
    assert.equal(s.states[`Transcription${direction}`].data, false);
    assert.equal(s.states[`Transcription${direction}`].state, "ok");
    const enable = `/set/enable/transcription_${direction === "Send" ? "send" : "receive"}`;
    assert.equal(s.calls.filter(([path]) => path === enable).length, 1);
    await s.click("google");
    s.render();
    assert.deepEqual(s.calls.at(-1), ["/set/data/selected_transcription_engine", "Google"]);
    assert.equal(s.calls.filter(([path]) => path === enable).length, 1, "writing the selection is not an ack");
    s.acknowledge("Google");
    assert.equal(s.render(), null);
    assert.equal(s.calls.filter(([path]) => path === enable).length, 2);
    s.render();
    assert.equal(s.calls.filter(([path]) => path === enable).length, 2, "one continuation only");
});

test("Whisper saves the selection and opens the existing download consent without restarting capture", async context => {
    const s = await fixture(context);
    s.firstEnable("Receive");
    await s.click("whisper");
    s.acknowledge("Whisper");
    const review = find(s.render(), node => node.type === "download-consent");
    assert.equal(review.props.kind, "whisper");
    assert.equal(review.props.weightType, "base");
    assert.equal(s.calls.filter(([path]) => path.startsWith("/set/enable/")).length, 1);
    assert.ok(!s.calls.some(([path]) => path.startsWith("/run/download")), "opening the review does not download");
    review.props.onDownload({ weight_type: "base", consent: true, manifest_version: "fake" });
    review.props.onCancel();
    s.render();
    assert.equal(s.calls.filter(([path]) => path.startsWith("/set/enable/")).length, 1);
});

for (const pending of [false, true]) test(`cancel leaves transcription off (selection pending: ${pending})`, async context => {
    const s = await fixture(context);
    s.firstEnable("Send");
    if (pending) await s.click("google");
    s.click("cancel");
    s.acknowledge("Google");
    assert.equal(s.render(), null);
    assert.equal(s.states.TranscriptionSend.data, false);
    assert.equal(s.calls.filter(([path]) => path.startsWith("/set/enable/")).length, 1);
});

test("Escape cancels and the initial focus target is Cancel", async context => {
    const s = await fixture(context);
    s.firstEnable("Send");
    const tree = s.render();
    assert.equal(find(tree, node => node.props?.autoFocus).props.children, "transcription_consent.cancel");
    let prevented = false;
    find(tree, node => node.type === "dialog").props.onCancel({ preventDefault: () => { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(s.render(), null);
    assert.equal(s.calls.filter(([path]) => path.startsWith("/set/enable/")).length, 1);
});

test("repeated choices and simultaneous enables do not multiply the continuation", async context => {
    const s = await fixture(context);
    s.firstEnable("Send");
    s.firstEnable("Receive");
    await s.click("google");
    await s.click("google");
    s.acknowledge("Google");
    assert.equal(s.calls.filter(([path]) => path === "/set/data/selected_transcription_engine").length, 1);
    assert.equal(s.calls.filter(([path]) => path === "/set/enable/transcription_send").length, 2);
    assert.equal(s.calls.filter(([path]) => path === "/set/enable/transcription_receive").length, 1);
});

test("failed save and unrelated selection updates never enable capture", async context => {
    const s = await fixture(context);
    s.firstEnable("Send");
    await s.click("google");
    s.acknowledge(null);
    assert.ok(find(s.render(), node => node.type === "dialog"));
    s.acknowledge("Google");
    assert.equal(s.calls.filter(([path]) => path.startsWith("/set/enable/")).length, 1);
});

test("mapped missing-model errors open review; unmount drops any continuation", async context => {
    const s = await fixture(context);
    s.error({ error_code: "TRANSCRIPTION_MODEL_MISSING", endpoint: "/set/enable/transcription_send", data: false });
    assert.ok(find(s.render(), node => node.type === "download-consent"));
    s.runtime.unmount();
    assert.equal(s.consent.useTranscriptionConsent().request, null);
    assert.deepEqual(s.calls, []);
});

test("only enable errors can open the chooser", async context => {
    const s = await fixture(context);
    s.error({ error_code: "TRANSCRIPTION_ENGINE_NOT_SELECTED", endpoint: "/get/data/selected_transcription_engine", data: false });
    assert.equal(s.render(), null);
});

test("settings show the selected engine and the Google transmission notice", async context => {
    const s = await fixture(context);
    const { TranscriptionEngine_Box } = await loadModule(new URL("../../views/app/config_page/setting_section/setting_box/transcription/Transcription.jsx", import.meta.url), s.runtime, {
        "@logics_configs": s.configs, "@utils": {},
        "../advanced_settings/SpeechServers": {}, "./RealtimeASRSettings": {},
        "../../../../../../logics/configs/cloudTranscription": { CLOUD_TRANSCRIPTION_ENGINES: [] },
        "../_templates/Templates": { RadioButtonContainer: "radio-options" }, "../_components": {},
        "../_components/compute_device/ComputeDevice": {}, "../_components/description/Description": {},
        "../_components/download_models/LegacyModelDownloadDialog": {}, "../shared_items/SharedItems": {},
    });
    s.transcription.currentSelectedTranscriptionEngine = { data: "Google", state: "ok" };
    const tree = s.runtime.render(TranscriptionEngine_Box);
    assert.equal(find(tree, node => node.type === "radio-options").props.checked_variable.data, "Google");
    assert.ok(find(tree, node => node.props?.children === "transcription_consent.google_notice"));
    s.transcription.currentSelectedTranscriptionEngine = { data: null, state: "ok" };
    assert.ok(find(s.runtime.render(TranscriptionEngine_Box), node => node.props?.role === "status"));
});

for (const language of ["en", "ja"]) test(`${language}: choice and error text disclose Google and the separate local download`, async () => {
    const messages = yaml.load(await readFile(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
    assert.match(messages.transcription_consent.google_notice, /Google/);
    assert.match(messages.transcription_consent.google_notice, language === "ja" ? /送られます/ : /sends/);
    assert.match(messages.transcription_consent.whisper_notice, language === "ja" ? /もう一度オン/ : /on again/);
    for (const code of ["ENGINE_NOT_SELECTED", "MODEL_MISSING", "ENGINE_UNAVAILABLE"])
        assert.ok(messages.backend_errors[`TRANSCRIPTION_${code}`]);
});
