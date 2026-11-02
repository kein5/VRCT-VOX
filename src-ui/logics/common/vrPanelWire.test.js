import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeLogUpdate, decodeOrdered, diffLogRows, encodeLogUpdate, encodeOrdered, isLogUpdate, isRelayAllowed, isSecretAtomName } from "./vrPanelWire.js";

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
        "/set/data/websocket_host", "/set/data/websocket_port", "/set/data/obs_browser_source_port", "/set/data/osc_ip_address",
        "/set/data/osc_port", "/set/data/voice_settings", "/set/data/direct_voice_settings", "/set/data/speech_server_settings",
        "/set/data/realtime_asr_settings"]) assert.equal(isRelayAllowed(path), false, path);
    for (const path of ["/get/data/openai_compatible_url", "/set/data/selected_font_family"]) assert.equal(isRelayAllowed(path), true, path);
});

test("credentials are not mirrored to the VR panel", () => {
    for (const name of ["DeepLAuthKey", "OpenAICompatibleAuthKey", "DeepgramAuthKey", "WebsocketAuthToken"]) assert.equal(isSecretAtomName(name), true, name);
    for (const name of ["SelectedFontFamily", "MessageLogs", "OpenAICompatibleUrl", "SelectedTranslationEngines"]) assert.equal(isSecretAtomName(name), false, name);
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
