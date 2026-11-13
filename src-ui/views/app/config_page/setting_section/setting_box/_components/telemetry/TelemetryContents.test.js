import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { hooks, loadModule, find } from "../../../../../../../logics/test/hookHarness.js";
import * as rows from "../../../../../../../logics/common/telemetryRows.js";

const EVENT = { event: "app_started", v: 2, timestamp: "2026-11-13T00:00:00Z", app_version: "0.1.0-beta.6", os: "Windows",
    os_version: "10.0.26320", locale: "ja-JP", hw: { cpu: "CPU", cores: 12, gpus: [] } };
const ERROR = { ...EVENT, event: "error", error_code: "speech_server_out_of_memory" };

async function setup(context, preview, props = {}) {
    const runtime = hooks(), asked = [];
    const { TelemetryContents } = await loadModule(new URL("./TelemetryContents.jsx", import.meta.url), runtime, {
        "@logics_configs": { useOthers: () => ({ currentTelemetryPreview: preview, getTelemetryPreview: () => asked.push(true) }) },
        "../../../../../../../logics/common/telemetryRows": rows,
    });
    context.after(() => runtime.unmount());
    return { tree: runtime.render(TelemetryContents, props), asked };
}

const all = (tree, predicate) => {
    const found = [];
    find(tree, node => { if (predicate(node)) found.push(node); return false; });
    return found;
};
const text = node => React.Children.toArray(node.props.children).join("");

test("what is sent is asked for when the user opens it, not before", async context => {
    const s = await setup(context, { state: "ok", data: null });
    assert.equal(s.tree.type, "details");
    assert.equal(text(find(s.tree, node => node.type === "summary")), "telemetry_contents.show");
    assert.deepEqual(s.asked, []);
    s.tree.props.onToggle({ currentTarget: { open: true } });
    assert.deepEqual(s.asked, [true]);
    // Closing it asks for nothing.
    s.tree.props.onToggle({ currentTarget: { open: false } });
    assert.deepEqual(s.asked, [true]);
    // Until the answer comes there is a status, not an empty box.
    for (const preview of [{ state: "ok", data: null }, { state: "pending", data: null }, { state: "pending", data: {} }]) {
        const waiting = await setup(context, preview);
        assert.equal(text(find(waiting.tree, node => node.props?.role === "status")), "telemetry_contents.loading");
        assert.equal(find(waiting.tree, node => node.type === "dl"), null);
    }
    const failed = await setup(context, { state: "ok", data: { endpoint: null, sent: [] } });
    assert.equal(text(find(failed.tree, node => node.props?.role === "status")), "telemetry_contents.unavailable");
});

test("the event is shown field by field and as the data itself", async context => {
    const s = await setup(context, { state: "ok", data: { endpoint: "https://example.invalid/v1/events", app_started: EVENT, sent: [] } });
    const list = find(s.tree, node => node.type === "dl");
    const shown = all(list, node => node.type === "dt").map(text);
    assert.deepEqual(shown, rows.telemetryRows(EVENT, key => key).map(row => row.label));
    assert.deepEqual(all(list, node => node.type === "dd").map(text), rows.telemetryRows(EVENT, key => key).map(row => row.value));
    // The data itself, exactly: nothing is sent that this does not show.
    const raw = find(s.tree, node => node.type === "pre");
    assert.deepEqual(JSON.parse(text(raw)), EVENT);
    // Reachable by keyboard, since it can be longer than its box.
    assert.equal(raw.props.tabIndex, 0);
    const paragraphs = all(s.tree, node => node.type === "p").map(text);
    // What the event holds, then what the receiver records beside it (the time it arrived and the country).
    assert.deepEqual(paragraphs, ["telemetry_contents.intro", "telemetry_contents.error_note", "telemetry_contents.destination",
        "telemetry_contents.receiver_note"]);
    // In the notice, nothing has been sent yet: no list of it.
    assert.equal(find(s.tree, node => node.type === "section"), null);
});

test("the settings also list what was sent, newest first, each with its data", async context => {
    const none = await setup(context, { state: "ok", data: { endpoint: null, app_started: EVENT, sent: [] } }, { with_sent: true });
    const empty = find(none.tree, node => node.type === "section");
    assert.equal(empty.props["aria-label"], "telemetry_contents.sent_title");
    assert.deepEqual(all(empty, node => node.type === "p").map(text), ["telemetry_contents.sent_none"]);
    // Without a destination (nothing can be sent), no destination line is shown.
    assert.equal(all(none.tree, node => node.type === "p").map(text).includes("telemetry_contents.destination"), false);

    const sent = [{ at: "2026-11-13 09:00", accepted: true, body: EVENT }, { at: "2026-11-14 21:30", accepted: false, body: ERROR }];
    const s = await setup(context, { state: "ok", data: { endpoint: null, app_started: EVENT, sent } }, { with_sent: true });
    const section = find(s.tree, node => node.type === "section");
    const items = all(section, node => node.type === "li");
    assert.deepEqual(items.map(item => text(find(item, node => node.type === "summary"))), [
        "2026-11-14 21:30 — telemetry_contents.events.error (speech_server_out_of_memory) — telemetry_contents.sent_failed",
        "2026-11-13 09:00 — telemetry_contents.events.app_started — telemetry_contents.sent_accepted",
    ]);
    assert.deepEqual(items.map(item => JSON.parse(text(find(item, node => node.type === "pre")))), [ERROR, EVENT]);
    // The list given by the backend is not reordered in place.
    assert.equal(sent[0].body, EVENT);
});
