import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { hooks, loadModule, find } from "../../../../../../../logics/test/hookHarness.js";

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
