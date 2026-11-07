import assert from "node:assert/strict";
import { test } from "node:test";
import { loadBridgeRoutes } from "./test/bridgeHarness.js";
import { expectBackendExit } from "./common/sidecarExitExpectation.js";
import { createSidecarSessionOwner } from "./common/sidecarSession.js";
import { loadModule } from "./test/hookHarness.js";

test("blocked config loading shows the persistent load-failure notice", async () => {
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/config_save_failed", status: 200,
        result: { reason: "load_failed", path: "/settings/config.json" } });
    assert.deepEqual(s.notices, [{ type: "error", key: "common_error.config_save_failed.load_failed",
        options: { hide_duration: null, category_id: "config_save_failed" } }]);
});

test("skipped speech warns when the backend count rises, not for earlier counts", async () => {
    const status = { expired: 2 };
    const s = await loadBridgeRoutes(undefined, null, null, () => status);
    s.rerender();
    assert.deepEqual(s.notices, []);
    status.expired = 3;
    s.rerender();
    assert.deepEqual(s.notices, [{ type: "warning", key: "voice_ui.speech_expired", options: { category_id: "speech_expired" } }]);
    s.rerender();
    assert.equal(s.notices.length, 1);
    status.expired = 0; // a restarted backend counts from zero
    s.rerender();
    assert.equal(s.notices.length, 1);
    status.expired = 1;
    s.rerender();
    assert.equal(s.notices.length, 2);
});

test("failed required initialization maps and scalars retain renderable defaults and warn", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    const fields = ["selected_your_languages", "selected_target_languages", "selected_tab_no",
        "selected_translation_engines", "ui_scaling", "auto_mic_select", "ui_language"];
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200,
        result: Object.fromEntries(fields.map(name => [`/get/data/${name}`, null])) });
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_UiScaling).data, 100);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_EnableAutoMicSelect).data, true);
    assert.equal(s.runtime.store.get(s.stores.Atom_SelectedPresetTabNumber).data, "1");
    const { LanguageSelectorOpenButton } = await loadModule(new URL("../views/app/main_page/sidebar_section/language_settings/language_selector_open_button/LanguageSelectorOpenButton.jsx", import.meta.url), s.runtime, {
        "@store": s.stores,
        "@useI18n": { useI18n: () => ({ t: key => key, i18n: { language: "en" } }) },
        "../../../../../../logics/common/languageNames.js": { createLanguageNames: () => ({ name: value => value }) },
        "@logics_main": { useLanguageSettings: () => ({
            ...s.stores.useStore_SelectedPresetTabNumber(), ...s.stores.useStore_SelectedYourLanguages(), ...s.stores.useStore_SelectedTargetLanguages(),
        }) },
    });
    for (const selector_key of ["your_language", "target_language"]) {
        assert.doesNotThrow(() => s.runtime.render(LanguageSelectorOpenButton, { selector_key, target_key: "1", TurnedOnSvgComponent: "svg" }));
    }
    assert.equal(s.notices.length, 1);
    assert.equal(s.notices[0].key, "common_warning.startup_degraded");
    assert.equal(errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable").length, fields.length);
});

test("malformed nested language maps and required scalar types cannot replace defaults", async context => {
    context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    const your = s.runtime.store.get(s.stores.Atom_SelectedYourLanguages);
    const target = s.runtime.store.get(s.stores.Atom_SelectedTargetLanguages);
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selected_your_languages": { 1: null, 2: {}, 3: {} },
        "/get/data/selected_target_languages": { ...target.data, 2: { 1: target.data[2][1] } },
        "/get/data/selected_tab_no": "4", "/get/data/ui_scaling": "100", "/get/data/auto_mic_select": 1,
    } });
    assert.strictEqual(s.runtime.store.get(s.stores.Atom_SelectedYourLanguages), your);
    assert.strictEqual(s.runtime.store.get(s.stores.Atom_SelectedTargetLanguages), target);
    assert.equal(s.runtime.store.get(s.stores.Atom_SelectedPresetTabNumber).data, "1");
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_UiScaling).data, 100);
    assert.equal(s.notices.length, 1);
});

test("valid language maps, compute-device objects, false and zero survive initialization", async () => {
    const s = await loadBridgeRoutes();
    const your = structuredClone(s.runtime.store.get(s.stores.Atom_SelectedYourLanguages).data);
    your["2"]["1"] = { language: "Japanese", country: "Japan", enable: true };
    const device = { device_name: "CPU", device: "cpu", device_index: 0, compute_types: ["int8"] };
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selected_your_languages": your, "/get/data/selected_tab_no": "2",
        "/get/data/selected_translation_compute_device": device,
        "/get/data/selectable_language_list": [{ language: "Japanese", country: "Japan" }],
        "/get/data/auto_mic_select": false, "/get/data/mic_threshold": 0,
        "/get/data/custom_whisper_auth_key": null, "/get/data/selected_custom_whisper_model": null,
        "/get/data/selected_transcription_engine": null,
    } });
    assert.deepEqual(s.runtime.store.get(s.stores.Atom_SelectedYourLanguages).data, your);
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SelectedTranslationComputeDevice).data, device);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_EnableAutoMicSelect).data, false);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_MicThreshold).data, 0);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_CustomWhisperAuthKey).data, null);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SelectedCustomWhisperModel).data, null);
    assert.deepEqual(s.notices, []);
});

test("message format objects from the backend survive initialization", async () => {
    const s = await loadBridgeRoutes();
    const format = { message: { prefix: "[", suffix: "]" }, separator: " / ",
        translation: { prefix: "", separator: "\n", suffix: "" }, translation_first: true };
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/send_message_format_parts": format,
        "/get/data/received_message_format_parts": format,
    } });
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SendMessageFormatParts).data, format);
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_ReceivedMessageFormatParts).data, format);
    assert.deepEqual(s.notices, []);
});

test("a failed message format getter keeps a format the settings page can render", async context => {
    context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/send_message_format_parts": null,
    } });
    const { message, translation } = s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SendMessageFormatParts).data;
    assert.equal(message.prefix, "");
    assert.equal(translation.suffix, "");
    assert.equal(s.notices.length, 1);
});

test("null init getter retains its real default, applies later fields, reaches ready and warns once", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    const hostAtom = s.stores.dynamicStoreRegistry.Atom_MicHostList;
    const before = s.runtime.store.get(hostAtom);
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selectable_mic_host_list": null,
        "/get/data/selectable_mic_device_list": ["Microphone"],
        "/get/data/selected_mic_host": "System",
    } });
    assert.strictEqual(s.runtime.store.get(hostAtom), before);
    assert.deepEqual(before.data, []);
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_MicDeviceList).data, { Microphone: "Microphone" });
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SelectedMicHost).data, "System");
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.deepEqual(s.notices, [{ type: "warning", key: "common_warning.startup_degraded",
        options: { hide_duration: null, category_id: "startup_degraded" } }]);
    const fieldErrors = errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable");
    assert.equal(fieldErrors.length, 1);
    assert.equal(fieldErrors[0].arguments[1], "/get/data/selectable_mic_host_list");
});

test("malformed arrays and individual handler errors do not abort remaining initialization", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selectable_mic_host_list": {},
        // A malformed member throws in the real arrayToObject transform.
        "/get/data/selectable_mic_device_list": [{ toString: null }],
        "/get/data/selected_mic_host": "System",
    } });
    assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_MicDeviceList).data, []);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_SelectedMicHost).data, "System");
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.equal(s.notices.length, 1);
    assert.equal(errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable").length, 2);
});

test("a valid initialization finishes without a degraded notice", async () => {
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/selectable_mic_host_list": [], "/get/data/auto_mic_select": false,
    } });
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.equal(s.runtime.store.get(s.stores.dynamicStoreRegistry.Atom_EnableAutoMicSelect).data, false);
    assert.deepEqual(s.notices, []);
});

test("unset scalar values (no API key, no model) are applied and do not warn", async context => {
    const errors = context.mock.method(console, "error", () => {});
    const s = await loadBridgeRoutes();
    s.receiveRoutes({ endpoint: "/run/initialization_complete", status: 200, result: {
        "/get/data/deepl_auth_key": null, "/get/data/selected_openai_model": null,
        "/get/data/selectable_mic_host_list": [],
    } });
    assert.equal(s.runtime.store.get(s.stores.Atom_IsBackendReady).data, true);
    assert.deepEqual(s.notices, []);
    assert.equal(errors.mock.calls.filter(call => call.arguments[0] === "Sidecar initialization field unavailable").length, 0);
});

for (const endpoint of ["/run/update_software", "/run/update_cuda_software"]) {
    for (const status of [400, 404, 409, 423, 500]) test(`${endpoint} ${status} clears expected exit and a later crash is reported`, async context => {
        context.mock.method(console, "error", () => {});
        const s = await loadBridgeRoutes(), events = {}, crashes = [];
        const owner = createSidecarSessionOwner({ store: s.stores.store,
            createCommand: () => ({ on: (name, fn) => { events[name] = fn; },
                stdout: { on: (_, fn) => { events.stdout = fn; } }, stderr: { on: () => {} }, spawn: async () => ({}) }),
            setInterval: () => 1, clearInterval: () => {},
        });
        const detach = owner.attach(() => ({ setStartupState: () => {}, beginStartup: () => {}, started: () => {},
            receiveRoutes: s.receiveRoutes, backendStopped: s.backendStopped, unexpectedExit: event => crashes.push(event) }));
        await s.stores.store.backend_session.completion;
        events.stdout(JSON.stringify({ endpoint: "/run/initialization_complete", status: 200, result: {} }));
        const session = s.stores.store.backend_session;
        expectBackendExit(session, endpoint);
        s.runtime.store.set(s.stores.Atom_IsSoftwareUpdating, { state: "ok", data: true });
        s.receiveRoutes({ endpoint, status, result: { error_code: "UPDATE_SOFTWARE_DOWNLOAD" } });
        assert.equal(session.expectedExits.size, 0);
        assert.equal(s.runtime.store.get(s.stores.Atom_IsSoftwareUpdating).data, false);
        events.close({ code: 1 });
        assert.equal(crashes.length, 1);
        detach();
    });
}
