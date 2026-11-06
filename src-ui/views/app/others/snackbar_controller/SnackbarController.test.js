import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, stubGlobals } from "../../../../logics/test/hookHarness.js";

const setup = async context => {
    const runtime = hooks(), toasts = [], timers = [];
    stubGlobals(context, { setTimeout: callback => { timers.push(callback); } });
    context.after(() => runtime.unmount());
    const notification = runtime.jotai.atom({ state: "ok", data: { status: "", is_open: false, message: "" } });
    let closes = 0;
    const { SnackbarController } = await loadModule(new URL("./SnackbarController.jsx", import.meta.url), runtime, {
        "@common_components": { CloseButton: "close-button" },
        "./ReactToastifyOverrideClass.scss": {},
        "react-toastify": { ToastContainer: "toasts", cssTransition: () => ({}), toast: (message, options) => toasts.push({ message, options }) },
        "@store": { Atom_NotificationStatus: notification },
        "@logics_common": { useNotificationStatus: () => ({ closeNotification: () => {
            closes++;
            runtime.store.set(notification, old => ({ ...old, data: { ...old.data, is_open: false } }));
        } }) },
    });
    const show = (message, extra = {}) => runtime.store.set(notification,
        { state: "ok", data: { status: "error", is_open: true, category_id: null, message, options: {}, ...extra } });
    const flush = () => timers.splice(0).forEach(callback => callback());
    return { runtime, render: () => runtime.render(SnackbarController), notification, toasts, show, flush, closes: () => closes };
};

test("notifications raised in the same tick each get their own toast", async context => {
    const s = await setup(context);
    s.render();
    // e.g. several hotkeys that failed to register at launch, reported in one loop
    s.show("first"); s.show("second"); s.show("third", { category_id: "third_id", status: "warning" });
    s.render();
    s.flush();
    assert.deepEqual(s.toasts.map(item => [item.message, item.options.toastId, item.options.type]),
        [["first", "first", "error"], ["second", "second", "error"], ["third", "third_id", "warning"]]);
});

test("closing or republishing a notification does not show it again, and unmount stops listening", async context => {
    const s = await setup(context);
    s.render();
    s.show("only");
    s.flush();
    assert.equal(s.toasts.length, 1);
    // A republish keeps the same notification object.
    s.runtime.store.set(s.notification, old => ({ ...old }));
    s.toasts[0].options.onClose();
    assert.equal(s.closes(), 1);
    s.render();
    s.flush();
    assert.equal(s.toasts.length, 1);
    s.runtime.unmount();
    s.show("after unmount");
    s.flush();
    assert.equal(s.toasts.length, 1);
});
