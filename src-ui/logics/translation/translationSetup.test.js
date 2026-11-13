import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../test/hookHarness.js";
import { downloadProgress } from "../main/setupNeeds.js";

const noop = () => {};
const api = values => new Proxy(values, { get: (object, name) => object[name] ?? noop });

async function fixture(context) {
    const runtime = hooks(), calls = [], notices = [];
    const setup = await loadModule(new URL("./useTranslationSetup.js", import.meta.url), runtime);
    const states = {};
    const mainStore = { store: { backend_subprocess: {} } };
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
    const translation = api({
        currentCTranslate2WeightTypeStatus: { data: [{ id: "small", is_downloaded: false }] },
        currentSelectedCTranslate2WeightType: { data: "small", state: "ok" },
        pendingCTranslate2WeightTypeStatus: id => { weight({ is_pending: true }); calls.push(["pending", id]); },
        downloadCTranslate2WeightTypeStatus: value => calls.push(["/run/download_ctranslate2_weight", value]),
    });
    const weight = values => { translation.currentCTranslate2WeightTypeStatus = { data: [{
        ...translation.currentCTranslate2WeightTypeStatus.data[0], ...values }] }; };
    const configs = { useTranslation: () => translation, ocrStartErrorKey: () => null, ocrShouldRestoreSharedWindow: () => false };
    for (const name of ["Transcription", "Others", "Ocr", "OcrSharedWindow", "AdvancedSettings"]) configs[`use${name}`] = () => api({});
    const common = { useNotificationStatus: () => api({
        showNotification_Error: (message, options) => notices.push(["error", options?.category_id]),
        showNotification_Success: (message, options) => notices.push(["success", message]),
    }) };
    for (const name of ["Volume", "LLMConnection", "IsSoftwareUpdating"]) common[`use${name}`] = () => api({});
    const errors = await loadModule(new URL("../_useBackendErrorHandling.js", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t: key => key, i18n: { exists: () => true } }) },
        "@logics_common": common, "@logics_configs": configs, "@logics_main": main,
        "./ui_configs": {}, "./configs/legacyModelConsent": {}, "./configs/cloudTranscription": { CLOUD_TRANSCRIPTION_ENGINES: [] },
        "./transcription/useTranscriptionConsent": { useTranscriptionConsent: () => ({ setRequest: noop }) },
        "./translation/useTranslationSetup": setup,
    });
    const error = errors._useBackendErrorHandling().errorHandling_Backend;
    let selector = false;
    const { TranslationSetupController } = await loadModule(new URL("../../views/app/_app_controllers/TranslationSetupController.jsx", import.meta.url), runtime, {
        "@logics_configs": configs, "@logics_main": main, "@logics_common": common,
        "@store": { useStore_IsOpenedTranslatorSelector: () => ({ updateIsOpenedTranslatorSelector: value => { selector = value; } }) },
        "../../../logics/translation/useTranslationSetup": setup,
        "../../../logics/main/setupNeeds": { downloadProgress },
        "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog": { LegacyModelDownloadDialog: "review" },
    });
    const render = () => runtime.render(TranslationSetupController);
    const press = () => {
        main.useMainFunction().toggleTranslation();
        error({ error_code: "TRANSLATION_MODEL_MISSING", endpoint: "/set/enable/translation", data: false });
        return render();
    };
    const accept = review => { review.props.onDownload({ weight_type: "small", consent: true }); review.props.onCancel(); render(); };
    const enables = () => calls.filter(([path]) => path === "/set/enable/translation").length;
    context.after(() => runtime.unmount());
    render();
    return { render, press, accept, enables, calls, notices, states, weight, setup, error, selector: () => selector };
}

test("turning Translation on without its model opens the review instead of a notice", async context => {
    const s = await fixture(context);
    assert.equal(s.render(), null);
    const review = s.press();
    assert.equal(review.type, "review");
    assert.equal(review.props.kind, "ctranslate2");
    assert.equal(review.props.weightType, "small");
    assert.equal(review.props.note, "studio.setup_translation_resume", "the review says the switch will be turned on");
    assert.deepEqual(s.notices, []);
    assert.deepEqual(s.states.Translation, { data: false, state: "ok" }, "the switch settles off");
    assert.ok(!s.calls.some(([path]) => path.startsWith("/run/download")), "opening the review does not download");
});

test("after consent the switch is turned on once, when the model has arrived", async context => {
    const s = await fixture(context);
    s.accept(s.press());
    assert.equal(s.render(), null);
    assert.deepEqual(s.calls.slice(-2), [["pending", "small"], ["/run/download_ctranslate2_weight", { weight_type: "small", consent: true }]]);
    assert.equal(s.enables(), 1, "nothing is retried while the model is on its way");
    s.weight({ progress: 40 });
    s.render();
    assert.equal(s.enables(), 1);
    s.weight({ is_downloaded: true, is_pending: false, progress: null });
    s.render();
    assert.equal(s.enables(), 2);
    assert.deepEqual(s.notices, [["success", "studio.setup_translation_ready"]]);
    s.render();
    assert.equal(s.enables(), 2, "one continuation only");
});

test("a cancelled or failed download leaves Translation off, even if the model arrives later", async context => {
    const s = await fixture(context);
    s.accept(s.press());
    s.weight({ is_pending: false, progress: null });
    s.render();
    s.weight({ is_downloaded: true });
    s.render();
    assert.equal(s.enables(), 1);
    assert.deepEqual(s.notices, []);
});

test("going back, or choosing another translator, downloads nothing and leaves Translation off", async context => {
    const s = await fixture(context);
    s.press().props.onCancel();
    assert.equal(s.render(), null);
    const review = s.press();
    review.props.onCancel();
    review.props.extraAction.onClick();
    assert.equal(s.selector(), true);
    assert.equal(review.props.extraAction.label, "studio.setup_other_translator");
    assert.ok(!s.calls.some(([path]) => path.startsWith("/run/download")));
    assert.equal(s.states.Translation.data, false);
});

test("a review opened from the empty conversation fetches the model without turning Translation on", async context => {
    const s = await fixture(context);
    s.setup.useTranslationSetup().open(false);
    assert.equal(s.render().props.note, null, "the review keeps saying nothing is turned on");
    s.accept(s.render());
    s.weight({ is_downloaded: true, is_pending: false, progress: null });
    s.render();
    assert.equal(s.enables(), 0);
    assert.deepEqual(s.notices, []);
});

test("a missing model reported for anything but the switch is a notice, as before", async context => {
    const s = await fixture(context);
    s.error({ error_code: "TRANSLATION_MODEL_MISSING", endpoint: "/run/send_message_box", data: false });
    assert.equal(s.render(), null);
    assert.deepEqual(s.notices, [["error", "TRANSLATION_MODEL_MISSING"]]);
});
