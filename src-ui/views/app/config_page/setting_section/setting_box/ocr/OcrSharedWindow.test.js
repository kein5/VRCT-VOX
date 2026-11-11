import assert from "node:assert/strict";
import { test } from "node:test";
import { find, hooks, loadModule } from "../../../../../../logics/test/hookHarness.js";
import * as sharedWindow from "../../../../../../logics/configs/ocrSharedWindow.js";

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const buttons = tree => {
    const found = [];
    const walk = node => {
        if (!node || typeof node !== "object") return;
        if (Array.isArray(node)) return node.forEach(walk);
        if (node.type === "button") found.push(node);
        walk(node.props?.children);
    };
    walk(tree);
    return found;
};

const mount = async (context, state) => {
    const runtime = hooks();
    context.after(() => runtime.unmount());
    const page = { state: { ...sharedWindow.INITIAL_SHARED_WINDOW, ...state }, calls: [] };
    const { OcrSharedWindow } = await loadModule(new URL("./OcrSharedWindow.jsx", import.meta.url), runtime, {
        "@logics_configs": { useOcrSharedWindow: () => ({
            currentOcrSharedWindow: { data: page.state },
            refresh: () => page.calls.push(["refresh"]),
            share: options => page.calls.push(["share", options]),
            stop: async () => { page.calls.push(["stop"]); },
        }) },
        "../../../../../../logics/configs/ocrSharedWindow": sharedWindow,
        "../_components/env_readout/EnvReadout": { EnvReadout: props => ({ type: "readout", props }) },
    });
    const render = () => runtime.render(OcrSharedWindow);
    return { page, render };
};

test("nothing is shown where no window can be shared, and opening the page asks for nothing", async context => {
    for (const supported of [null, false]) {
        const { page, render } = await mount(context, { supported });
        assert.equal(render(), null);
        assert.deepEqual(page.calls, [["refresh"]]);
    }
});

test("the button asks for a window only when it is pressed", async context => {
    const { page, render } = await mount(context, { supported: true });
    const tree = render();
    assert.equal(tree.type, "section");
    assert.equal(tree.props["aria-label"], "config_page.ocr.shared_window.label");
    const [share, ...others] = buttons(tree);
    assert.equal(others.length, 0);
    assert.equal(share.props.children, "config_page.ocr.shared_window.share");
    assert.equal(share.props.type, "button");
    assert.deepEqual(page.calls, [["refresh"]]);
    share.props.onClick();
    // The saved choice may be restored: this is "share", not "choose another".
    assert.deepEqual(page.calls.at(-1), ["share", { choose: false }]);
});

test("while a window is shared the user can choose another one or stop", async context => {
    const { page, render } = await mount(context, { supported: true, active: true });
    const [another, stop] = buttons(render());
    assert.equal(another.props.children, "config_page.ocr.shared_window.share_another");
    another.props.onClick();
    assert.deepEqual(page.calls.at(-1), ["share", { choose: true }]);
    assert.equal(stop.props.children, "config_page.ocr.shared_window.stop");
    await stop.props.onClick();
    await flush();
    assert.deepEqual(page.calls.at(-1), ["stop"]);
});

test("while the desktop's dialog is open the button stays focusable but does nothing", async context => {
    const { page, render } = await mount(context, { supported: true, busy: true });
    const [share, ...others] = buttons(render());
    assert.equal(others.length, 0);
    assert.equal(share.props["aria-disabled"], true);
    assert.equal(share.props.disabled, undefined);
    share.props.onClick();
    assert.deepEqual(page.calls, [["refresh"]]);
});

test("the status and a failure are announced in the readout", async context => {
    const { render } = await mount(context, { supported: true, error: "screencast_helper_missing" });
    const readout = find(render(), node => node.type?.name === "EnvReadout" || node.props?.tone);
    assert.equal(readout.props.tone, "failed");
    const lines = [].concat(readout.props.children).filter(Boolean).map(line => line.props.children);
    assert.deepEqual(lines, ["config_page.ocr.shared_window.status_idle", "config_page.ocr.shared_window.error_failed"]);
});
