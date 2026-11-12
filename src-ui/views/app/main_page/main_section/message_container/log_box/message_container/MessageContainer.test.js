import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { hooks, loadModule, find } from "../../../../../../../logics/test/hookHarness.js";
import { applyRealtimeCaption } from "../../../../../../../logics/transcription/realtimeCaptionState.js";
import { encodeLogUpdate, decodeLogUpdate } from "../../../../../../../logics/common/vrPanelWire.js";

test("realtime outcomes render the same row and labels in desktop and VR log mirrors", async () => {
    const runtime = hooks(), store = { is_vr_panel: false };
    const { MessageContainer } = await loadModule(new URL("./MessageContainer.jsx", import.meta.url), runtime, {
        "@store": { store }, "./message_sub_menu_container/MessageSubMenuContainer": {},
    });
    for (const source of ["mic", "speaker"]) {
        const event = { source, generation: 4, namespace: "session", item_id: "one", revision: 1, state: "final", text: "認識した文" };
        const owner = { [source]: { generation: 4, namespace: "session", requested: true } };
        const pending = applyRealtimeCaption({ rows: [], retired: [] }, event, owner);
        const encoded = encodeLogUpdate(null, { state: "ok", data: pending.rows });
        const mirror = decodeLogUpdate(null, encoded.message);
        for (const isVr of [false, true]) {
            store.is_vr_panel = isVr;
            const node = runtime.render(MessageContainer.type, (isVr ? mirror.rows : pending.rows)[0]);
            assert.ok(find(node, n => n.props.children === `main_page.message_log.${source === "mic" ? "sending" : "processing"}`));
            assert.equal(Boolean(find(node, n => n.props.className === "loader")), !isVr);
        }
        for (const [outcome, reason, micLabel, speakerLabel] of [
            ["delivered", null, "sent", "received"],
            ["delivered", "vrchat_off", "sent_vrchat_off", "received"],
            ["not_delivered", "expired", "not_sent_expired", "processing_stopped"],
            ["not_delivered", "revoked", "not_sent_revoked", "processing_stopped"],
            ["not_delivered", "superseded", "not_sent_superseded", "processing_stopped"],
            ["not_delivered", "filtered", "not_sent_filtered", "processing_stopped"],
            ["failed", "processing_failed", "send_unconfirmed", "processing_failed"],
        ]) {
            const settled = applyRealtimeCaption(pending, { ...event, revision: 3, state: "outcome", outcome, reason }, {});
            const update = encodeLogUpdate(encoded.sent, { state: "ok", data: settled.rows });
            const mirrored = decodeLogUpdate(mirror, update.message);
            assert.deepEqual(mirrored.rows, settled.rows);
            for (const isVr of [false, true]) {
                store.is_vr_panel = isVr;
                const node = runtime.render(MessageContainer.type, (isVr ? mirrored.rows : settled.rows)[0]);
                const label = find(node, n => n.props.children === `main_page.message_log.${source === "mic" ? micLabel : speakerLabel}`);
                assert.ok(label);
                assert.equal(find(node, n => n.props.className === "loader"), null);
                if (outcome === "failed") assert.match(label.props.className, /failed/);
                if (outcome === "not_delivered") assert.match(label.props.className, /not_sent/);
                assert.equal(/vrchat_off/.test(label.props.className), reason === "vrchat_off" && source === "mic");
            }
        }
    }
});

test("VR pending label is static; only the desktop renders the animated loader", async () => {
    const runtime = hooks(), store = { is_vr_panel: true };
    const { MessageContainer } = await loadModule(new URL("./MessageContainer.jsx", import.meta.url), runtime, {
        "@store": { store }, "./message_sub_menu_container/MessageSubMenuContainer": {},
    });
    const props = { id: "pending", category: "sent", status: "pending", created_at: "12:00",
        messages: { original: { message: "Hello", transliteration: [] }, translations: [] } };
    const vr = runtime.render(MessageContainer.type, props);
    assert.equal(find(vr, node => node.props.className === "loader"), null);
    const label = find(vr, node => node.props.children === "main_page.message_log.sending");
    assert.ok(label);
    assert.equal(label.props.className, "category sent_message");
    const css = await readFile(new URL("./MessageContainer.module.scss", import.meta.url), "utf8");
    assert.doesNotMatch(css.slice(css.indexOf(".category {")), /animation:|@include loader/);
    store.is_vr_panel = false;
    const desktop = runtime.render(MessageContainer.type, props);
    assert.ok(find(desktop, node => node.props.className === "loader"));
    assert.match(css, /\.loader\s*\{\s*@include loader/);
    for (const isVr of [false, true]) {
        store.is_vr_panel = isVr;
        const failed = runtime.render(MessageContainer.type, { ...props, status: "failed" });
        const failure = find(failed, node => node.props.children === "main_page.message_log.send_unconfirmed");
        assert.match(failure.props.className, /failed/);
        assert.equal(find(failed, node => node.props.className === "loader"), null);
        assert.equal(find(failed, node => node.props.children === "main_page.message_log.sent"), null);
    }
});

test("a typed message kept out of the chatbox by the setting says so, quietly and only once settled", async () => {
    const runtime = hooks();
    const { MessageContainer } = await loadModule(new URL("./MessageContainer.jsx", import.meta.url), runtime, {
        "@store": { store: { is_vr_panel: false } }, "./message_sub_menu_container/MessageSubMenuContainer": {},
    });
    const row = { id: "typed", category: "sent", created_at: "12:00",
        messages: { original: { message: "Hello", transliteration: [] }, translations: [] } };
    const label = props => find(runtime.render(MessageContainer.type, { ...row, ...props }),
        node => typeof node.props?.children === "string" && node.props.children.startsWith("main_page.message_log."));
    const off = label({ status: "ok", delivery_reason: "vrchat_off" });
    assert.equal(off.props.children, "main_page.message_log.sent_vrchat_off");
    assert.match(off.props.className, /vrchat_off/);
    assert.doesNotMatch(off.props.className, /failed|not_sent/, "the user's own setting is not a fault");
    assert.equal(label({ status: "ok" }).props.children, "main_page.message_log.sent");
    assert.equal(label({ status: "pending", delivery_reason: "vrchat_off" }).props.children, "main_page.message_log.sending");
    assert.equal(label({ status: "failed", delivery_reason: "vrchat_off" }).props.children, "main_page.message_log.send_unconfirmed");
    assert.equal(label({ status: "ok", category: "received", delivery_reason: "vrchat_off" }).props.children, "main_page.message_log.received");
});
