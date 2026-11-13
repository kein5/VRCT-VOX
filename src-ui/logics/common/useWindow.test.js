import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, stubGlobals } from "../test/hookHarness.js";
import * as windowGeometry from "./windowGeometry.js";

// innerSize reports physical pixels; the 800px breakpoint is in CSS pixels
// (scaled by the UI size), like the stylesheet's (max-width: 800px) queries.
for (const [physical, ratio, scaling, narrow] of [
    [1200, 1.5, 100, true], [1202, 1.5, 100, false],
    [1600, 2, 100, true], [1700, 2, 100, false],
    [800, 1, 100, true], [801, 1, 100, false],
    [1800, 1.5, 150, true], [1801, 1.5, 150, false],
]) test(`a ${physical}px window at devicePixelRatio ${ratio} and UI ${scaling}% is ${narrow ? "narrow" : "wide"}`, async context => {
    const attributes = new Set(), updates = [];
    stubGlobals(context, { devicePixelRatio: ratio, document: { documentElement: {
        hasAttribute: name => attributes.has(name),
        toggleAttribute: (name, on) => { if (on) attributes.add(name); else attributes.delete(name); },
    } } });
    const { useWindow } = await loadModule(new URL("./useWindow.js", import.meta.url), hooks(), {
        "@tauri-apps/api/window": {},
        "@store": { store: { appWindow: { innerSize: async () => ({ width: physical }) } },
            useStore_IsBreakPoint: () => ({ updateIsBreakPoint: value => updates.push(value) }) },
        "@logics_configs": { useAppearance: () => ({ currentUiScaling: { data: scaling } }) },
        "./windowGeometry.js": windowGeometry,
    });
    await useWindow().asyncUpdateBreakPoint();
    assert.equal(attributes.has("data-narrow"), narrow);
    assert.deepEqual(updates, narrow ? [true] : []);
});

// The saved geometry is in physical pixels. At 125% the built-in 870x654 was a
// 696x523 CSS pixel window: the narrow layout on the first launch.
test("the first window is sized in CSS pixels inside the work area; a saved one is restored as it was", async () => {
    const calls = [];
    class PhysicalPosition { constructor(x, y) { Object.assign(this, { x, y }); } }
    class PhysicalSize { constructor(width, height) { Object.assign(this, { width, height }); } }
    const monitor = { position: { x: 0, y: 0 }, size: { width: 1280, height: 800 }, scaleFactor: 1.25,
        workArea: { position: { x: 0, y: 0 }, size: { width: 1280, height: 740 } } };
    const { useWindow } = await loadModule(new URL("./useWindow.js", import.meta.url), hooks(), {
        "@tauri-apps/api/window": { availableMonitors: async () => [monitor], currentMonitor: async () => monitor, PhysicalPosition, PhysicalSize },
        "@store": { store: { appWindow: {
            setPosition: async position => calls.push(["position", position.x, position.y]),
            setSize: async size => calls.push(["size", size.width, size.height]),
        } }, useStore_IsBreakPoint: () => ({ updateIsBreakPoint() {} }) },
        "@logics_configs": { useAppearance: () => ({ currentUiScaling: { data: 100 } }) },
        "./windowGeometry.js": windowGeometry,
    });
    await useWindow().restoreWindowGeometry({ x_pos: 0, y_pos: 0, width: 870, height: 654 });
    // 870x654 CSS pixels are 1088x818 here; the height stops at the taskbar.
    assert.deepEqual(calls, [["position", 0, 0], ["size", 1088, 740]]);
    calls.length = 0;
    await useWindow().restoreWindowGeometry({ x_pos: 40, y_pos: 30, width: 870, height: 654 });
    assert.deepEqual(calls, [["position", 40, 30], ["size", 870, 654]]);
});

const loadClosing = async (runtime, appWindow, sent) => loadModule(new URL("./useWindow.js", import.meta.url), runtime, {
    "@tauri-apps/api/window": {},
    "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: endpoint => sent.push(endpoint) }) },
    "@store": { store: { appWindow }, useStore_IsBreakPoint: () => ({ updateIsBreakPoint() {} }) },
    "@logics_configs": { useAppearance: () => ({ currentUiScaling: { data: 100 } }) },
    "./windowGeometry.js": windowGeometry,
});

test("Alt+F4 and the close button share one shutdown before the window is destroyed", async context => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), sent = [], calls = [];
    let requested = null;
    const appWindow = {
        onCloseRequested: async handler => { requested = handler; return () => calls.push("unlisten"); },
        destroy: async () => calls.push("destroy"),
        close: async () => calls.push("close"),
    };
    const { WindowCloseController, useWindow } = await loadClosing(runtime, appWindow, sent);
    runtime.render(WindowCloseController);
    await Promise.resolve();

    let prevented = false;
    requested({ preventDefault: () => { prevented = true; } }); // Alt+F4
    useWindow().asyncCloseApp(); // and the title bar button while it waits
    assert.equal(prevented, true);
    assert.deepEqual(sent, ["/run/shutdown"]);
    assert.deepEqual(calls, []); // the backend gets its time to save first
    context.mock.timers.tick(2000);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(calls, ["destroy"]);
    runtime.unmount();
    assert.deepEqual(calls, ["destroy", "unlisten"]);
});

test("a failed destroy removes the listener and closes the window the usual way", async context => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    stubGlobals(context, { console: { ...console, error() {} } });
    const runtime = hooks(), sent = [], calls = [];
    const appWindow = {
        onCloseRequested: async () => () => calls.push("unlisten"),
        destroy: async () => { throw new Error("not allowed"); },
        close: async () => calls.push("close"),
    };
    const { WindowCloseController, useWindow } = await loadClosing(runtime, appWindow, sent);
    runtime.render(WindowCloseController);
    await Promise.resolve();
    const closed = useWindow().asyncCloseApp();
    context.mock.timers.tick(2000);
    await closed;
    assert.deepEqual(calls, ["unlisten", "close"]);
});
