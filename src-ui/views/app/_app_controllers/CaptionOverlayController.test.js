import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../../../logics/test/hookHarness.js";
import { flush } from "../../../logics/test/bridgeHarness.js";
import * as lines from "../../../logics/captionOverlay/lines.js";
import * as ioFlow from "../../../logics/flow/ioFlow.js";
import * as flowText from "../../../logics/flow/flowText.js";

const t = (key, options) => options ? `${key}:${JSON.stringify(options)}` : key;

const row = (id, category, message, status = "ok") => ({
    id, category, status, messages: { original: { message, transliteration: [] }, translations: [] },
});

async function setup(context, { supported = true } = {}) {
    context.mock.timers.enable({ apis: ["Date"], now: 1_000_000 });
    const runtime = hooks(), calls = [];
    const state = { ready: true, enabled: false, rows: [], onlyTranslated: false,
        settings: { position: "bottom", font_size: 28, display_duration: 6, opacity: 0.6 },
        flow: { desktop: false, count: 1 }, traces: [], map: null };
    const invoke = async (command, args) => {
        calls.push([command, args]);
        return command === "caption_overlay_supported" ? supported : undefined;
    };
    const { CaptionOverlayController } = await loadModule(new URL("./CaptionOverlayController.jsx", import.meta.url), runtime, {
        "@tauri-apps/api/core": { invoke },
        "@store": { useStore_MessageLogs: () => ({ currentMessageLogs: { data: state.rows } }) },
        "@useI18n": { useI18n: () => ({ t }) },
        "@logics_common": { useIsBackendReady: () => ({ currentIsBackendReady: { data: state.ready } }) },
        "@logics_configs": {
            useAppearance: () => ({ currentSelectedFontFamily: { data: "Yu Gothic UI" } }),
            useVr: () => ({
                currentIsEnabledOverlayDesktop: { data: state.enabled },
                currentOverlayDesktopSettings: { data: state.settings },
                currentOverlayShowOnlyTranslatedMessages: { data: state.onlyTranslated },
                currentIoFlowOverlaySettings: { data: state.flow },
            }),
        },
        "../../../logics/captionOverlay/lines": lines,
        "../../../logics/flow/useIoFlow": { useIoFlow: () => ({ currentIoFlow: { data: state.map }, currentIoTraces: { data: state.traces } }) },
        "../../../logics/flow/ioFlow.js": ioFlow,
        "../../../logics/flow/flowText.js": flowText,
    });
    const render = async () => {
        runtime.render(CaptionOverlayController); await flush();
        runtime.render(CaptionOverlayController); await flush();
    };
    await render();
    context.after(() => runtime.unmount());
    return { state, calls, render, tick: ms => context.mock.timers.tick(ms),
        of: name => calls.filter(([command]) => command === name).map(([, args]) => args) };
}

test("the window opens only while the setting is on, and closes when it is turned off", async context => {
    const s = await setup(context);
    assert.deepEqual(s.of("caption_overlay_set"), [{ open: false, position: "bottom" }]);
    assert.deepEqual(s.of("caption_overlay_update"), []);
    s.state.enabled = true;
    await s.render();
    assert.deepEqual(s.of("caption_overlay_set").at(-1), { open: true, position: "bottom" });
    s.state.settings = { ...s.state.settings, position: "top" };
    await s.render();
    assert.deepEqual(s.of("caption_overlay_set").at(-1), { open: true, position: "top" });
    s.state.enabled = false;
    await s.render();
    assert.deepEqual(s.of("caption_overlay_set").at(-1), { open: false, position: "top" });
});

test("the backend not being ready keeps the window closed", async context => {
    const s = await setup(context);
    s.state.enabled = true; s.state.ready = false;
    await s.render();
    assert.equal(s.of("caption_overlay_set").every(args => args.open === false), true);
    assert.deepEqual(s.of("caption_overlay_update"), []);
});

test("where the overlay is not supported, nothing is opened or sent", async context => {
    const s = await setup(context, { supported: false });
    s.state.enabled = true; s.state.rows = [row(1, "sent", "こんにちは")];
    await s.render();
    assert.deepEqual(s.calls.map(([command]) => command), ["caption_overlay_supported"]);
});

test("rows already in the log are not shown; new rows get the display time and carry the look", async context => {
    const s = await setup(context);
    s.state.rows = [row(1, "sent", "前からあった行"), row(2, "system", "保存しました")];
    s.state.enabled = true;
    await s.render();
    const first = s.of("caption_overlay_update").at(-1).snapshot;
    assert.deepEqual(first.lines.map(line => [line.id, line.until]), [["1", 0]]);
    assert.deepEqual([first.position, first.font_size, first.opacity, first.font_family], ["bottom", 28, 0.6, "Yu Gothic UI"]);

    s.tick(5000);
    s.state.rows = [...s.state.rows, row(3, "received", "Hello")];
    await s.render();
    const second = s.of("caption_overlay_update").at(-1).snapshot;
    assert.deepEqual(second.lines.map(line => [line.id, line.kind, line.text, line.until]),
        [["1", "sent", "前からあった行", 0], ["3", "received", "Hello", 1_000_000 + 5000 + 6000]]);

    // Turning the overlay off and on again treats the log as history once more.
    s.state.enabled = false;
    await s.render();
    s.state.enabled = true;
    await s.render();
    assert.deepEqual(s.of("caption_overlay_update").at(-1).snapshot.lines.map(line => line.until), [0, 0]);
});

const trace = (id, input, at) => ({ id, input, text: `text ${id}`, translation: "", origin: "send", stages: {},
    outputs: { chatbox: { state: "sent", at_ms: at } } });

test("the flow strip opens the window without captions, and lists the newest inputs up to the setting", async context => {
    const s = await setup(context);
    s.state.rows = [row(1, "sent", "字幕にはしない")];
    s.state.traces = [trace("a", "voice", 300), trace("b", "chat", 120)];
    s.state.map = { conversion_round_trip_ms: 31 };
    s.state.flow = { desktop: true, count: 1 };
    await s.render();
    assert.deepEqual(s.of("caption_overlay_set").at(-1), { open: true, position: "bottom" });
    let snapshot = s.of("caption_overlay_update").at(-1).snapshot;
    assert.deepEqual(snapshot.lines, [], "captions stay off");
    assert.deepEqual(snapshot.flow.map(item => [item.id, item.input, item.rows[0].value]), [["b", "chat", "120 ms"]]);
    assert.equal(snapshot.flow_note, 'io_flow.conversion_live:{"ms":31}');
    s.state.flow = { desktop: true, count: 3 };
    await s.render();
    snapshot = s.of("caption_overlay_update").at(-1).snapshot;
    assert.deepEqual(snapshot.flow.map(item => item.id), ["b", "a"]);
    // With the strip off the snapshot is as before: no flow at all.
    s.state.flow = { desktop: false, count: 3 };
    s.state.enabled = true;
    await s.render();
    snapshot = s.of("caption_overlay_update").at(-1).snapshot;
    assert.equal("flow" in snapshot, false);
});
