import assert from "node:assert/strict";
import test from "node:test";
import { eventTarget, find, hooks, loadModule } from "../../logics/test/hookHarness.js";

async function launcher(context) {
    const runtime = hooks(), document = eventTarget(), window = eventTarget();
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const previousDocument = globalThis.document, previousWindow = globalThis.window;
    globalThis.document = document;
    globalThis.window = window;
    context.after(() => {
        runtime.unmount();
        if (previousDocument === undefined) delete globalThis.document;
        else globalThis.document = previousDocument;
        if (previousWindow === undefined) delete globalThis.window;
        else globalThis.window = previousWindow;
    });
    const calls = [];
    const { VrLauncher } = await loadModule(new URL("./VrLauncher.jsx", import.meta.url), runtime, {
        "@logics_common": {
            useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: false } }),
            useVrPanelLogOutOfView: () => ({ currentVrPanelLogOutOfView: { data: false } }),
            useVrPanelLauncherIntro: () => ({ currentVrPanelLauncherIntro: { data: "idle" } }),
        },
        "@logics_main": { useMainFunction: () => ({}) },
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: path => calls.push(path) }) },
        "@images/brand/icon-small.svg": "icon",
        "@images/brand/logo-en.svg": "logo-en", "@images/brand/logo-ja.svg": "logo-ja", "@images/brand/logo-ko.svg": "logo-ko",
        "@images/brand/logo-zh-Hant.svg": "logo-zh-Hant", "@images/brand/logo-zh-Hans.svg": "logo-zh-Hans",
        "./VrTooltip": { VrTooltipButton: "button" },
    });
    const tree = runtime.render(VrLauncher, { windows: { log: false, popup: null },
        toggleLog: () => calls.push("toggleLog"), openLog: () => calls.push("openLog"), togglePopup() {} });
    const logButton = find(tree, node => typeof node.props?.onLongPress === "function");
    assert.ok(logButton);
    const render = () => runtime.render(logButton.type, logButton.props);
    render();
    return { runtime, document, window, calls, render };
}

for (const signal of ["outside-release", "document-leave", "pointer-cancel", "window-blur", "button-leave", "button-blur", "unmount"]) {
    test(`launcher hold is cancelled by ${signal} before openLog/recall`, async context => {
        const view = await launcher(context);
        view.render().props.onMouseDown({ button: 0 });
        assert.match(view.render().props.className, /is_holding/);
        context.mock.timers.tick(599);
        if (signal === "outside-release") view.document.dispatch("mouseup", { button: 0, clientX: -1, clientY: -1 });
        if (signal === "document-leave") view.document.dispatch("mouseleave", {});
        if (signal === "pointer-cancel") view.document.dispatch("pointercancel", {});
        if (signal === "window-blur") view.window.dispatch("blur", {});
        if (signal === "button-leave") view.render().props.onMouseLeave();
        if (signal === "button-blur") view.render().props.onBlur();
        if (signal === "unmount") view.runtime.unmount();
        context.mock.timers.tick(1000);
        assert.deepEqual(view.calls, []);
        if (signal !== "unmount") assert.doesNotMatch(view.render().props.className, /is_holding/);
    });
}

test("launcher short click and intentional 600 ms hold retain their actions", async context => {
    const view = await launcher(context);
    view.render().props.onMouseDown({ button: 0 });
    context.mock.timers.tick(100);
    view.document.dispatch("mouseup", { button: 0 });
    view.render().props.onMouseUp();
    view.render().props.onClick();
    assert.deepEqual(view.calls, ["toggleLog"]);
    context.mock.timers.tick(1000);
    assert.deepEqual(view.calls, ["toggleLog"]);
    view.render().props.onMouseDown({ button: 0 });
    context.mock.timers.tick(599);
    assert.deepEqual(view.calls, ["toggleLog"]);
    context.mock.timers.tick(1);
    assert.deepEqual(view.calls, ["toggleLog", "openLog", "/run/vr_panel_recall_log"]);
    view.document.dispatch("mouseup", { button: 0 });
    view.render().props.onClick();
    context.mock.timers.tick(1000);
    assert.deepEqual(view.calls, ["toggleLog", "openLog", "/run/vr_panel_recall_log"]);
});

test("a cancelled hold can start again on the next primary press", async context => {
    const view = await launcher(context);
    view.render().props.onMouseDown({ button: 0 });
    context.mock.timers.tick(300);
    view.document.dispatch("mouseup", { button: 0, clientX: -1, clientY: -1 });
    view.render().props.onMouseDown({ button: 2 });
    context.mock.timers.tick(1000);
    assert.deepEqual(view.calls, []);
    view.render().props.onMouseDown({ button: 0 });
    context.mock.timers.tick(600);
    assert.deepEqual(view.calls, ["openLog", "/run/vr_panel_recall_log"]);
});

test("launcher cancellation listeners stay stable across renders and clean up on unmount", async context => {
    const view = await launcher(context);
    for (let i = 0; i < 3; i++) view.render();
    assert.deepEqual(view.document.added.map(([type]) => type), ["mouseup", "mouseleave", "pointercancel"]);
    assert.deepEqual(view.window.added.map(([type]) => type), ["blur"]);
    view.runtime.unmount();
    assert.deepEqual(view.document.removed, view.document.added);
    assert.deepEqual(view.window.removed, view.window.added);
});
