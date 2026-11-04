import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import i18next from "i18next";
import { parsePortInput, PORT_INPUT_LIMITS } from "./networkPortInput.js";
import { buildObsBrowserSourceUrl } from "./obsBrowserSourceUrl.js";
import { hooks, loadModule, find } from "../test/hookHarness.js";
import { loadBridgeRoutes } from "../test/bridgeHarness.js";

test("port drafts accept only digits in range and serialize as integers", () => {
    for (const [value, expected] of [[0, null], [1, 1], [65535, 65535], [65536, null], [-1, null],
        [true, null], [1.5, null], ["80", 80], ["8x", null], ["1.0", null], ["1e2", null],
        ["-1", null], ["+1", null], ["", null], [" 80", null], ["８０", null]]) {
        assert.equal(parsePortInput(value), expected, String(value));
    }
    assert.deepEqual(PORT_INPUT_LIMITS, { min: 1, max: 65535, step: 1 });
});

const box = "../../views/app/config_page/setting_section/setting_box/";
async function settingsHarness() {
    const runtime = hooks(), drafts = [], sent = [], copied = [];
    let saveOptions;
    const advanced = {};
    for (const name of ["OscPort", "WebsocketPort", "ObsBrowserSourcePort"]) {
        advanced[`current${name}`] = { state: "ok", data: 2231 };
        advanced[`set${name}`] = value => sent.push([name, value]);
    }
    Object.assign(advanced, {
        currentWebsocketHost: { data: "127.0.0.1" }, currentWebsocketAuthToken: { data: "test+token&あ" },
    });
    const module = await loadModule(new URL(box + "advanced_settings/AdvancedSettings.jsx", import.meta.url), runtime, {
        "./DirectVoiceSettings": { DirectVoiceSettings: () => null },
        "../shared_items/SharedItems": { AutoExportMessageLogsContainer: () => null },
        "../_components/description/Description": { Description: () => null },
        "../../../../../../logics/configs/obsBrowserSourceUrl": { buildObsBrowserSourceUrl },
        "../../../../../../logics/configs/networkPortInput": { parsePortInput, PORT_INPUT_LIMITS },
        "@logics_common": { useCopyToClipboard: () => ({ copyToClipboard: url => copied.push(url) }) },
        "@logics_configs": {
            useAdvancedSettings: () => advanced,
            useSaveButtonLogic: options => {
                saveOptions = options;
                return { variable: options.variable, onChangeFunction: value => drafts.push(value), saveFunction: () => {} };
            },
        },
        "../_templates/Templates": { EntryWithSaveButtonContainer: () => null, ActionButtonContainer: () => null },
        "../_components": { SectionLabelComponent: () => null },
    });
    const root = runtime.render(module.AdvancedSettings);
    const child = (tree, name) => find(tree, node => node.type?.name === name).type;
    const ws = runtime.render(child(root, "WebsocketContainer"));
    const obs = runtime.render(child(root, "ObsBrowserSourceContainer"));
    return { runtime, drafts, sent, copied, get saveOptions() { return saveOptions; },
        components: [module.OscPortContainer, child(ws, "WebsocketPortContainer"), child(obs, "ObsBrowserSourcePortContainer")],
        urlComponent: child(ws, "WebsocketUrlContainer"),
    };
}

test("all three production port fields enforce range and send numeric IPC values", async () => {
    const s = await settingsHarness();
    for (const component of s.components) {
        const row = s.runtime.render(component);
        assert.equal(row.props.type, "number");
        for (const key of ["min", "max", "step"]) assert.equal(row.props[key], PORT_INPUT_LIMITS[key]);
        s.drafts.length = 0;
        for (const value of ["0", "65536", "-1", "1.5", "1e2", "8x"]) row.props.onChangeFunction(value);
        assert.deepEqual(s.drafts, []);
        for (const value of ["", "1", "65535"]) row.props.onChangeFunction(value);
        assert.deepEqual(s.drafts, ["", "1", "65535"]);
        s.saveOptions.setFunction("80");
        assert.equal(s.sent.at(-1)[1], 80);
        s.saveOptions.setFunction("");
        assert.equal(s.sent.at(-1)[1], null); // backend returns existing localized invalid-port error
    }
});

test("native number input receives min, max and step through the shared components", async () => {
    const runtime = hooks();
    runtime.api.useImperativeHandle = () => {};
    const { _Entry } = await loadModule(new URL(box + "_components/_atoms/_entry/_Entry.jsx", import.meta.url), runtime);
    const { EntryWithSaveButton } = await loadModule(new URL(box + "_components/entry_with_save_button/EntryWithSaveButton.jsx", import.meta.url), runtime,
        { "../_atoms/_entry/_Entry": { _Entry } });
    const wrapper = runtime.render(EntryWithSaveButton, { type: "number", variable: 2231, ...PORT_INPUT_LIMITS });
    const entry = find(wrapper, node => node.type === _Entry);
    const tree = runtime.render(props => _Entry.render(props, null), entry.props);
    const input = find(tree, node => node.type === "input");
    for (const key of ["min", "max", "step"]) assert.equal(input.props[key], PORT_INPUT_LIMITS[key]);
});

test("WebSocket copy uses the exact token returned by the backend and masks only the display", async () => {
    const s = await settingsHarness();
    const row = s.runtime.render(s.urlComponent);
    row.props.onclickFunction();
    assert.equal(new URL(s.copied[0]).searchParams.get("token"), "test+token&あ");
    assert.ok(!JSON.stringify(row.props).includes("test+token"));
});

for (const language of ["en", "ja"]) {
    const translation = yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
    for (const [endpoint, code, field, previous] of [
        ["osc_port", "VALIDATION_OSC_PORT_INVALID", "OscPort", 9000],
        ["websocket_port", "WEBSOCKET_PORT_INVALID", "WebsocketPort", 2231],
        ["obs_browser_source_port", "OBS_BROWSER_SOURCE_PORT_INVALID", "ObsBrowserSourcePort", 2232],
        ["websocket_host", "VALIDATION_INVALID_IP", "WebsocketHost", "127.0.0.1"],
    ]) {
        test(`${language}: ${code} restores the setting and shows localized guidance`, async context => {
            context.mock.method(console, "error", () => {});
            const i18n = i18next.createInstance();
            await i18n.init({ lng: language, resources: { [language]: { translation } } });
            const s = await loadBridgeRoutes(undefined, i18n);
            const atom = s.stores.dynamicStoreRegistry[`Atom_${field}`];
            s.runtime.store.set(atom, { state: "pending", data: previous });
            s.receiveRoutes({ endpoint: `/set/data/${endpoint}`, status: 400,
                result: { error_code: code, data: previous } });
            assert.deepEqual(s.runtime.store.get(atom), { state: "ok", data: previous });
            const text = i18n.t(`backend_errors.${code}`);
            assert.ok(i18n.exists(`backend_errors.${code}`));
            assert.equal(s.notices[0].key, text);
            if (endpoint.endsWith("_port")) assert.match(text, /65535/);
        });
    }
    test(`${language}: WebSocket host label states IPv4`, () => {
        assert.match(translation.config_page.advanced_settings.websocket_host.label, /IPv4/);
    });
}
