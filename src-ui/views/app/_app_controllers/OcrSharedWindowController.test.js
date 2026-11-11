import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../../../logics/test/hookHarness.js";
import * as sharedWindow from "../../../logics/configs/ocrSharedWindow.js";

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

// The controller with the app around it replaced: chat reading's switch, the shared-window state,
// the Tauri event and the notifications.
const mount = async (context, { listenFails = false } = {}) => {
    const runtime = hooks();
    context.after(() => runtime.unmount());
    const app = { chatReading: { data: false, state: "ok" }, shared: { supported: true, active: false, busy: false, error: null },
        calls: [], notices: [], listeners: [], unlistened: 0 };
    const { OcrSharedWindowController } = await loadModule(new URL("./OcrSharedWindowController.jsx", import.meta.url), runtime, {
        "@tauri-apps/api/event": { listen: async (event, handler) => {
            if (listenFails) throw new Error("not inside the app");
            app.listeners.push([event, handler]);
            return () => { app.unlistened++; };
        } },
        "@logics_common": { useNotificationStatus: () => ({
            showNotification_Warning: (message, options) => app.notices.push(["warning", message, options]),
            showNotification_Error: (message, options) => app.notices.push(["error", message, options]),
        }) },
        "@logics_main": { useMainFunction: () => ({ currentOcrCaptureStatus: app.chatReading }) },
        "@logics_configs": { useOcrSharedWindow: () => ({
            currentOcrSharedWindow: { data: app.shared },
            refresh: () => app.calls.push("refresh"),
            stop: () => { app.calls.push("stop"); app.shared = { ...app.shared, active: false }; },
            ended: () => { app.calls.push("ended"); app.shared = { ...app.shared, active: false }; },
        }) },
        "../../../logics/configs/ocrSharedWindow": sharedWindow,
    });
    const render = () => runtime.render(OcrSharedWindowController);
    render();
    await flush();
    return { app, render, runtime };
};

test("mounting asks what is shared and never starts sharing", async context => {
    const { app } = await mount(context);
    assert.deepEqual(app.calls, ["refresh"]);
    assert.deepEqual(app.listeners.map(([event]) => event), ["screencast-ended"]);
});

test("turning chat reading off ends the sharing", async context => {
    const { app, render } = await mount(context);
    app.shared = { ...app.shared, active: true };
    app.chatReading = { data: true, state: "ok" };
    render();
    assert.deepEqual(app.calls, ["refresh"]);
    // Waiting for the backend's answer is not "off" yet.
    app.chatReading = { data: true, state: "pending" };
    render();
    assert.deepEqual(app.calls, ["refresh"]);
    app.chatReading = { data: false, state: "ok" };
    render();
    assert.deepEqual(app.calls, ["refresh", "stop"]);
    // Off stays off: nothing is stopped twice.
    render();
    assert.deepEqual(app.calls, ["refresh", "stop"]);
});

test("a chat reading start that fails leaves the shared window alone", async context => {
    const { app, render } = await mount(context);
    app.shared = { ...app.shared, active: true };
    app.chatReading = { data: false, state: "pending" };
    render();
    app.chatReading = { data: false, state: "ok" };
    render();
    assert.deepEqual(app.calls, ["refresh"]);
});

test("turning chat reading off with nothing shared stops nothing", async context => {
    const { app, render } = await mount(context);
    app.chatReading = { data: true, state: "ok" };
    render();
    app.chatReading = { data: false, state: "ok" };
    render();
    assert.deepEqual(app.calls, ["refresh"]);
});

test("the user is told when the desktop or the window ends the sharing", async context => {
    const { app } = await mount(context);
    const [, handler] = app.listeners[0];
    handler({ payload: { reason: "ended" } });
    assert.deepEqual(app.calls, ["refresh", "ended"]);
    assert.deepEqual(app.notices, [["warning", "config_page.ocr.shared_window.notice_ended", { category_id: "ocr_shared_window" }]]);
    handler({ payload: { reason: "failed" } });
    assert.deepEqual(app.notices[1], ["error", "config_page.ocr.shared_window.notice_failed", { category_id: "ocr_shared_window" }]);
});

test("the listener goes away with the controller, and a browser preview without Tauri is fine", async context => {
    const { app, runtime } = await mount(context);
    runtime.unmount();
    assert.equal(app.unlistened, 1);
    const preview = await mount(context, { listenFails: true });
    assert.deepEqual(preview.app.calls, ["refresh"]);
});
