import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../logics/test/hookHarness.js";
import { loadBridgeStore } from "../../../logics/test/bridgeHarness.js";
import { chunkArray } from "../../../logics/utils.js";
import * as routeState from "../../../logics/voice/routeState.js";

const icon = () => null;
const keydown = (control, key, repeat = false) => {
    let prevented = false;
    control.props.onKeyDown({ key, repeat, preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
};
const loadSwitches = async (b, voice = {}) => {
    const requests = [];
    const main = await loadModule(new URL("../../../logics/main/useMainFunction.js", import.meta.url), b.runtime, {
        "@store": b.stores,
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: endpoint => requests.push(endpoint) }) },
    });
    const switches = await loadModule(new URL("./sidebar_section/main_function_switch/MainFunctionSwitch.jsx", import.meta.url), b.runtime, {
        "@store": b.stores,
        "@logics_common": { useIsBackendReady: b.stores.useStore_IsBackendReady },
        "../../../../../logics/common/useNotificationStatus": { useNotificationStatus: () => ({ showNotification_Error() {} }) },
        "../../../../../logics/voice/useVoice": { useVoice: () => voice },
        "../../../../../logics/voice/routeState": routeState,
        "@logics_main": { ...main, useIsMainPageCompactMode: () => ({ currentIsMainPageCompactMode: { data: false } }) },
        "../../../../common_components/toggle_switch/ToggleSwitch": { ToggleSwitch: icon },
    });
    return { ...switches, ...main, requests };
};

for (const key of ["Enter", " "]) test(`holding ${JSON.stringify(key)} cannot restart a main function after its stop acknowledgement`, async () => {
    const b = await loadBridgeStore();
    b.stores.store.backend_subprocess = {};
    const s = await loadSwitches(b);
    for (const [name, endpoint] of [["Translation", "translation"], ["TranscriptionSend", "transcription_send"],
        ["TranscriptionReceive", "transcription_receive"], ["OcrCapture", "ocr_capture"]]) {
        const atom = b.stores[`Atom_${name}Status`];
        b.runtime.store.set(atom, { data: true, state: "ok" });
        const render = () => {
            const main = s.useMainFunction();
            return b.runtime.render(s.SwitchContainer, { SvgComponent: icon, currentState: main[`current${name}Status`],
                toggleFunction: main[`toggle${name}`] });
        };
        const before = s.requests.length, control = render();
        keydown(control, key);
        // Even a second fresh event before React renders must use the synchronous pending guard.
        keydown(control, key);
        assert.deepEqual(s.requests.slice(before), [`/set/disable/${endpoint}`]);
        b.runtime.store.set(atom, { data: false, state: "ok" });
        keydown(render(), key, true);
        assert.deepEqual(s.requests.slice(before), [`/set/disable/${endpoint}`]);
        keydown(render(), key);
        assert.deepEqual(s.requests.slice(before), [`/set/disable/${endpoint}`, `/set/enable/${endpoint}`]);
    }
});

test("TTS and RVC ignore held keys but allow a fresh press to cancel their pending starts", async () => {
    const b = await loadBridgeStore(), sent = [];
    b.stores.store.backend_subprocess = {};
    b.runtime.store.set(b.stores.Atom_IsBackendReady, { data: true, state: "ok" });
    const voice = { status: { tts_generation: 1 }, ttsPending: { intent: true }, directOwner: "rvc",
        directPending: { intent: true }, directState: { observation_id: "one", pending: true },
        send: endpoint => sent.push(endpoint) };
    const s = await loadSwitches(b, voice);
    for (const id of ["tts", "rvc"]) {
        const item = find(b.runtime.render(s.MainFunctionSwitch), node => node.props.switch_id === id);
        const control = s.SwitchContainer(item.props), before = sent.length;
        keydown(control, "Enter", true);
        keydown(control, " ", true);
        assert.equal(sent.length, before);
        keydown(control, "Enter");
        assert.equal(sent.at(-1), id === "tts" ? "/run/disable_tts" : "/run/stop_direct_voice");
    }
});

test("disconnected main switches hide retained activity and reject clicks, keys and stale handlers", async () => {
    const b = await loadBridgeStore(), sent = [];
    b.stores.store.backend_subprocess = {};
    b.runtime.store.set(b.stores.Atom_IsBackendReady, { data: true, state: "ok" });
    const voice = { status: { tts_enabled: true, tts_generation: 1 }, directOwner: "rvc",
        directState: { observation_id: "one", requested: true }, send: endpoint => sent.push(endpoint) };
    const s = await loadSwitches(b, voice);
    for (const name of ["Translation", "TranscriptionSend", "TranscriptionReceive", "OcrCapture"])
        b.runtime.store.set(b.stores[`Atom_${name}Status`], { data: true, state: "ok" });
    const live = b.runtime.render(s.MainFunctionSwitch);
    const main = s.useMainFunction();
    b.stores.store.backend_subprocess = null;
    b.stores.store.backend_stopped = true;
    b.runtime.store.set(b.stores.Atom_IsBackendReady, { data: false, state: "ok" });
    for (const item of live.props.children) item.props.toggleFunction();
    for (const name of ["Translation", "TranscriptionSend", "TranscriptionReceive", "OcrCapture"]) {
        main[`set${name}`](true);
        assert.deepEqual(b.runtime.store.get(b.stores[`Atom_${name}Status`]), { data: true, state: "ok" });
    }
    const disconnected = b.runtime.render(s.MainFunctionSwitch);
    for (const item of disconnected.props.children) {
        const control = s.SwitchContainer(item.props);
        assert.equal(control.props["aria-disabled"], true);
        assert.equal(control.props["aria-checked"], false);
        assert.equal(control.props["aria-busy"], false);
        assert.match(control.props["aria-label"], /main_page.backend_disconnected/);
        assert.doesNotMatch(control.props.className, /is_active/);
        assert.ok(find(control, node => node.props.children === "main_page.backend_disconnected"));
        control.props.onClick();
        keydown(control, "Enter");
        keydown(control, " ");
    }
    assert.deepEqual(s.requests, []);
    assert.deepEqual(sent, []);
});

test("VR main-function actions still use the mirrored transport without owning a child", async () => {
    const b = await loadBridgeStore();
    b.stores.store.is_vr_panel = true;
    const s = await loadSwitches(b);
    const main = s.useMainFunction();
    main.toggleTranscriptionSend();
    main.setTranscriptionReceive(false);
    assert.deepEqual(s.requests, ["/set/enable/transcription_send", "/set/disable/transcription_receive"]);
});

test("main language and log div buttons activate only on fresh Enter or Space presses", async () => {
    const runtime = hooks(), actions = [];
    let opened = false;
    const language = {
        canChangeLanguageSettings: () => true, isLanguageSettingsBusy: false,
        currentSelectedPresetTabNumber: { data: "1" },
        currentSelectedYourLanguages: { data: { "1": { "1": { language: "Japanese", country: "Japan" } } } },
        currentSelectedTargetLanguages: { data: { "1": { "1": { language: "English", enable: true }, "2": {}, "3": {} } } },
        currentTranslationEngines: { data: [{ id: "one", label: "One" }] },
        currentSelectedTranslationEngines: { data: { "1": "one" } },
        setSelectedPresetTabNumber: () => actions.push("preset"),
        setSelectedTranslationEngines: () => actions.push("engine"),
        swapSelectedLanguages: () => actions.push("swap"),
        addTargetLanguage: () => actions.push("add"), removeTargetLanguage: () => actions.push("remove"),
    };
    const imports = { "@logics_main": { useLanguageSettings: () => language }, "@utils": { chunkArray },
        "@store": { useStore_IsOpenedTranslatorSelector: () => ({ currentIsOpenedTranslatorSelector: { data: opened },
            updateIsOpenedTranslatorSelector: value => { opened = value; actions.push("open"); } }) },
        "./translator_selector/TranslatorSelector": {}, "@setting_box": { MessageLogUiScalingContainer: icon } };
    const cases = [
        ["sidebar_section/language_settings/preset_tab_selector/PresetTabSelector.jsx", "PresetTabSelector", {}],
        ["sidebar_section/language_settings/translator_selector_open_button/TranslatorSelectorOpenButton.jsx", "TranslatorSelectorOpenButton", {}],
        ["sidebar_section/language_settings/translator_selector_open_button/translator_selector/TranslatorSelector.jsx", "TranslatorSelector",
            { translation_engines: [{ id: "two", label: "Two", is_available: true }], selected_id: "one" }],
        ["sidebar_section/language_settings/language_swap_button/LanguageSwapButton.jsx", "LanguageSwapButton", {}],
        ["sidebar_section/language_settings/add_remove_target_language_buttons/AddRemoveTargetLanguageButtons.jsx", "AddRemoveTargetLanguageButtons", {}],
        ["main_section/message_container/message_log_settings_container/MessageLogSettingsContainer.jsx", "MessageLogSettingsContainer", {}],
    ];
    const controls = tree => {
        if (!tree || typeof tree !== "object") return [];
        if (typeof tree.type === "function") return controls(tree.type(tree.props));
        return [tree.props.role === "button" ? tree : null,
            ...[tree.props.children].flat(Infinity).flatMap(controls)].filter(Boolean);
    };
    for (const [path, name, props] of cases) {
        const module = await loadModule(new URL(path, import.meta.url), runtime, imports);
        for (const key of ["Enter", " "]) {
            const render = () => controls(runtime.render(module[name], props));
            for (let index = 0; index < render().length; index++) {
                const before = actions.length;
                keydown(render()[index], key);
                const after = actions.length;
                const expanded = render()[index].props["aria-expanded"];
                keydown(render()[index], key, true);
                assert.equal(actions.length, after, `${name}: ${key}`);
                assert.equal(render()[index].props["aria-expanded"], expanded, `${name}: ${key}`);
                assert.ok(after > before || expanded !== undefined);
            }
        }
    }
});
