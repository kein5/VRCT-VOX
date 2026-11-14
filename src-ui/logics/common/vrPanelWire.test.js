import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { decodeLogUpdate, decodeOrdered, diffLogRows, encodeLogUpdate, encodeOrdered, isLogUpdate, isRelayAllowed, isSecretAtomName,
    VR_PANEL_RELAY_PATHS, VR_PANEL_STATE_ATOMS, VR_PANEL_STATE_CATEGORIES, vrPanelStateNames } from "./vrPanelWire.js";
import { scanVrPanelState, settingsByCategory } from "../test/vrPanelStateScan.js";

// Tauri の emit を通ったときの変化を模す: キーを辞書順にし、undefined を落とし、NaN を null にする
const sortKeysDeep = value => Array.isArray(value) ? value.map(sortKeysDeep)
    : value && typeof value === "object" ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sortKeysDeep(value[key])])) : value;
const emitRoundTrip = value => JSON.parse(JSON.stringify(sortKeysDeep(value)));

test("object key order survives the emit round trip", () => {
    const fonts = { "Yu Gothic UI": "Yu Gothic UI", arial: "arial", Arial: "Arial", "メイリオ": "メイリオ" };
    const plain = emitRoundTrip(fonts);
    assert.notDeepEqual(Object.keys(plain), Object.keys(fonts)); // 素のままでは並びが変わる
    assert.deepEqual(Object.keys(decodeOrdered(emitRoundTrip(encodeOrdered(fonts)))), Object.keys(fonts));
});

test("nested atoms, arrays and primitives are restored unchanged", () => {
    const atom = { state: "ok", data: { devices: { b: "b", a: "a" }, list: [{ z: 1, a: [{ y: 2, x: null }] }, "text", 3, true, null] } };
    assert.deepEqual(decodeOrdered(emitRoundTrip(encodeOrdered(atom))), atom);
    assert.deepEqual(Object.keys(decodeOrdered(emitRoundTrip(encodeOrdered(atom))).data.devices), ["b", "a"]);
    assert.deepEqual(decodeOrdered(emitRoundTrip(encodeOrdered([1, "a"]))), [1, "a"]);
});

test("a value that was not encoded passes through", () => {
    assert.deepEqual(decodeOrdered({ a: 1 }), { a: 1 });
});

test("the VR panel can ask for settings and the main features, but not for dangerous operations", () => {
    for (const path of ["/set/enable/translation", "/set/data/overlay_vr_panel_opacity", "/get/data/selected_tab_no", "/run/vr_panel_windows",
        "/run/swap_your_language_and_target_language", "/set/enable/ocr_capture"]) assert.equal(isRelayAllowed(path), true, path);
    for (const path of ["/run/shutdown", "/run/update_software", "/run/open_filepath_logs", "/run/open_filepath_config_file",
        "/run/download_whisper_weight", "/run/update_cuda_software", "/run/download_ctranslate2_weight", "/set/data/deepl_auth_key", "/set/data/websocket_auth_token",
        "relative/path", "", undefined, 3]) assert.equal(isRelayAllowed(path), false, String(path));
});

test("the VR panel cannot change where saved keys are sent or what runs", () => {
    for (const path of ["/set/data/openai_compatible_url", "/set/data/lmstudio_url", "/set/data/ollama_url", "/set/data/custom_whisper_url",
        "/set/data/websocket_host", "/set/data/websocket_port", "/set/data/websocket_tls", "/set/data/obs_browser_source_port",
        "/set/data/osc_ip_address", "/set/data/osc_port", "/set/data/voice_settings", "/set/data/direct_voice_settings",
        "/set/data/speech_server_settings", "/set/data/realtime_asr_settings", "/set/data/ocr_portal_restore_token",
        "/get/data/ocr_portal_restore_token", "/get/data/openai_compatible_url", "/get/data/deepl_auth_key",
        "/run/regenerate_websocket_auth_token"]) assert.equal(isRelayAllowed(path), false, path);
});

// SEC-02: the main window relays "vr-panel-stdout" events. Only windows allowed to emit events
// can send one, and those must be the main window and the VR panel.
test("only the main window and the VR panel may emit the relayed events", () => {
    const dir = new URL("../../../src-tauri/capabilities/", import.meta.url);
    const emitting = ["core:default", "core:event:default", "core:event:allow-emit", "core:event:allow-emit-to"];
    for (const file of readdirSync(dir).filter(name => name.endsWith(".json"))) {
        const capability = JSON.parse(readFileSync(new URL(file, dir), "utf8"));
        const permissions = (capability.permissions ?? []).map(item => typeof item === "string" ? item : item.identifier);
        if (!permissions.some(permission => emitting.includes(permission))) continue;
        for (const window of capability.windows ?? []) assert.ok(["main", "vr_panel"].includes(window), `${file}: ${window} may emit events`);
    }
});

// SEC-07: consent to usage data is the user's answer in the main window, never a relayed request.
test("the VR panel cannot turn usage data on or answer its notice", () => {
    for (const path of ["/set/enable/telemetry", "/set/disable/telemetry", "/set/data/telemetry_notice",
        "/get/data/telemetry_preview"]) assert.equal(isRelayAllowed(path), false, path);
});

// SEC-02: a list of what is relayed, so that nothing else is, new endpoints included.
test("an endpoint the list does not name is not relayed", () => {
    for (const path of ["/set/data/a_setting_added_later", "/set/enable/a_feature_added_later", "/run/a_command_added_later",
        "/get/data/a_value_added_later", "/set/data/font_family/", "/SET/DATA/FONT_FAMILY", " /set/data/font_family"])
        assert.equal(isRelayAllowed(path), false, path);
});

// What the VR windows send, read from their source: every generated setter they call, the
// launcher's switches, the language window and the meters. If a VR window starts sending
// something new, this fails until the path is added to VR_PANEL_RELAY_PATHS on purpose.
test("everything the VR windows send is relayed", () => {
    const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
    const settings = new Map([...read("../configs/config_page_setter/ui_config_setter.js")
        .matchAll(/\{[^{}]*?Base_Name:\s*"(\w+)"[^{}]*?logics_template_id:\s*"(\w+)"[^{}]*?base_endpoint_name:\s*"(\w+)"[^{}]*?\}/gs)]
        .map(([, base, template, endpoint]) => [base, { template, endpoint }]));
    const handWritten = {
        toggleTranslation: ["translation"], toggleTranscriptionSend: ["transcription_send"],
        toggleTranscriptionReceive: ["transcription_receive"], toggleOcrCapture: ["ocr_capture"],
        setSelectedPresetTabNumber: "/set/data/selected_tab_no", setSelectedYourLanguages: "/set/data/selected_your_languages",
        setTargetLanguagesInOrder: "/set/data/selected_target_languages",
        setSelectedTranslationEngines: "/set/data/selected_translation_engines",
        swapSelectedLanguages: "/run/swap_your_language_and_target_language",
        refreshLanguageSettings: ["/get/data/selected_tab_no", "/get/data/selected_your_languages", "/get/data/selected_target_languages",
            "/get/data/selected_translation_engines", "/get/data/selectable_translation_engines"],
        volumeCheckStart_Mic: "/set/enable/check_mic_threshold", volumeCheckStop_Mic: "/set/disable/check_mic_threshold",
        volumeCheckStart_Speaker: "/set/enable/check_speaker_threshold", volumeCheckStop_Speaker: "/set/disable/check_speaker_threshold",
    };
    const endpointsOf = name => {
        const known = handWritten[name];
        if (Array.isArray(known)) return known.flatMap(item => item.startsWith("/") ? [item] : [`/set/enable/${item}`, `/set/disable/${item}`]);
        if (known) return [known];
        const [, verb, base] = name.match(/^(set|toggle)(\w+)$/) ?? [];
        const setting = settings.get(base);
        if (!setting) return [];
        return verb === "toggle" ? [`/set/enable/${setting.endpoint}`, `/set/disable/${setting.endpoint}`] : [`/set/data/${setting.endpoint}`];
    };
    const sent = new Set(), names = new Set();
    for (const file of readdirSync(new URL("../../views/vr/", import.meta.url)).filter(name => /\.jsx?$/.test(name) && !name.includes(".test."))) {
        const source = read(`../../views/vr/${file}`);
        for (const [path] of source.matchAll(/"\/(?:get|set|run)\/[a-z0-9_/]+"/g)) sent.add(JSON.parse(path));
        for (const [name] of source.matchAll(/\b(?:set|toggle)[A-Z]\w*|\bvolumeCheck\w+|\brefreshLanguageSettings\b|\bswapSelectedLanguages\b/g)) names.add(name);
    }
    for (const name of names) for (const path of endpointsOf(name)) sent.add(path);
    assert.ok(sent.size > 40, `found ${sent.size} paths: the source scan no longer matches the VR windows`);
    for (const path of sent) assert.equal(isRelayAllowed(path), true, `the VR panel sends ${path}`);
    // And nothing is listed that the VR windows never send.
    for (const path of VR_PANEL_RELAY_PATHS) assert.ok(sent.has(path), `${path} is listed but no VR window sends it`);
});

test("credentials are not mirrored to the VR panel", () => {
    for (const name of ["DeepLAuthKey", "OpenAICompatibleAuthKey", "DeepgramAuthKey", "WebsocketAuthToken",
        "OcrPortalRestoreToken"]) assert.equal(isSecretAtomName(name), true, name);
    for (const name of ["SelectedFontFamily", "MessageLogs", "OpenAICompatibleUrl", "SelectedTranslationEngines"]) assert.equal(isSecretAtomName(name), false, name);
});

// SEC-03: the VR panel gets only the state its views read. The scan reads the VR views' source
// and the hooks they use; a new atom the VR panel reads fails here until it is listed on purpose.
const settingsArray = () => Object.entries(settingsByCategory())
    .flatMap(([Category, bases]) => bases.map(Base_Name => ({ Category, Base_Name })));

test("the VR panel is sent every atom its views read", () => {
    const { atoms, categories, files } = scanVrPanelState();
    assert.ok(files.length > 20 && atoms.size > 10, `the scan found ${files.length} files and ${atoms.size} atoms`);
    const allowed = vrPanelStateNames(settingsArray());
    for (const category of categories) assert.ok(VR_PANEL_STATE_CATEGORIES.includes(category), `the VR panel reads the ${category} settings`);
    for (const name of atoms) assert.ok(allowed.has(name) || isSecretAtomName(name), `the VR panel reads ${name}`);
    // And nothing is listed that the VR views never read.
    for (const category of VR_PANEL_STATE_CATEGORIES) assert.ok(categories.has(category), `${category} is listed but no VR view reads it`);
    for (const name of VR_PANEL_STATE_ATOMS) assert.ok(atoms.has(name), `${name} is listed but no VR view reads it`);
});

test("the VR panel is not sent credentials, advanced settings, updates or hotkeys", () => {
    const settings = settingsArray();
    const allowed = vrPanelStateNames(settings);
    const advanced = settings.filter(setting => ["AdvancedSettings", "Updater"].includes(setting.Category)).map(setting => setting.Base_Name);
    assert.ok(advanced.length > 5, "the advanced settings were not found");
    for (const name of [...advanced, "WebsocketAuthToken", "DeepLAuthKey", "OcrPortalRestoreToken", "Hotkeys",
        "AvailableReleases", "LatestSoftwareVersionInfo", "SoftwareVersion", "ComputeMode"]) {
        assert.equal(allowed.has(name), false, name);
    }
    for (const name of allowed) assert.equal(isSecretAtomName(name), false, name);
    for (const name of ["MessageLogs", "VrPanelLayout", "SelectedYourLanguages", "MicVolume"]) assert.ok(allowed.has(name), name);
});

// SEC-03: the state goes through the VR panel's own channel, never an event other windows hear.
test("the state is pushed to the VR panel's channel, not emitted as an event", () => {
    const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
    const sender = read("../../views/app/_app_controllers/VrPanelSyncController.jsx");
    const receiver = read("../../views/vr/VrApp.jsx");
    assert.match(sender, /invoke\("vr_panel_state_push"/);
    assert.match(receiver, /invoke\("vr_panel_state_subscribe"/);
    for (const source of [sender, receiver]) assert.doesNotMatch(source, /["']vr-panel-state["']/);
    const rust = read("../../../src-tauri/src/vr_panel_state.rs");
    assert.match(rust, /sender != VR_PANEL/);
    assert.match(rust, /sender != MAIN/);
});

const row = (id, text = id) => ({ id, category: "sent", status: "ok", messages: { original: { message: text, transliteration: [] }, translations: [] } });

test("a log diff sends only the rows that changed", () => {
    const [a, b, c, d] = ["a", "b", "c", "d"].map(id => row(id));
    assert.deepEqual(diffLogRows([a, b], [a, b, c]), { drop: 0, keep: 2, rows: [c] }); // 追加
    assert.deepEqual(diffLogRows([a, b, c], [b, c, d]), { drop: 1, keep: 2, rows: [d] }); // 上限で先頭が落ちた
    const b2 = { ...b, status: "pending" };
    assert.deepEqual(diffLogRows([a, b, c], [a, b2, c]), { drop: 0, keep: 1, rows: [b2, c] }); // 途中の行が変わった
    assert.deepEqual(diffLogRows([a, b, c], [a, c]), { drop: 0, keep: 1, rows: [c] }); // 途中の行が消えた
    assert.deepEqual(diffLogRows([a, b], []), { drop: 2, keep: 0, rows: [] });
    assert.equal(diffLogRows([a, b], [row("a"), b]), null); // 先頭が作り直された
    assert.equal(diffLogRows([], [a]), null);
});

test("the VR panel rebuilds the same log from the diffs", () => {
    let sent = null, received = null, rows = [];
    const steps = [
        current => [...current, row("a")],
        current => [...current, row("b"), row("c")],
        current => current.map(item => item.id === "b" ? { ...item, status: "pending" } : item),
        current => [...current.slice(1), row("d")],
        current => current.filter(item => item.id !== "c"),
        () => [],
        current => [...current, row("e", "日本語")],
    ];
    for (const step of steps) {
        rows = step(rows);
        const update = encodeLogUpdate(sent, { state: "ok", data: rows });
        sent = update.sent;
        const encoded = emitRoundTrip(update.message);
        assert.equal(isLogUpdate(encoded), true);
        received = decodeLogUpdate(received, encoded);
        assert.deepEqual(received.rows, rows);
        assert.equal(received.state, "ok");
    }
});

test("a log diff against a log the VR panel did not receive is refused", () => {
    const first = encodeLogUpdate(null, { state: "ok", data: [row("a")] });
    const second = encodeLogUpdate(first.sent, { state: "ok", data: [...first.sent.rows, row("b")] });
    assert.equal(decodeLogUpdate(null, emitRoundTrip(second.message)), null); // 起動直後で全件をまだ受け取っていない
    const full = encodeLogUpdate(second.sent, { state: "ok", data: second.sent.rows }, true);
    assert.deepEqual(decodeLogUpdate(null, emitRoundTrip(full.message)).rows, second.sent.rows);
    assert.equal(isLogUpdate(encodeOrdered({ state: "ok", data: [] })), false);
});
