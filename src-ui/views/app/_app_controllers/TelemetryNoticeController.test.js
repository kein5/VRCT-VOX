import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../logics/test/hookHarness.js";

const TelemetryContents = () => null;

async function setup(context, notice) {
    const runtime = hooks(), sent = [], refreshed = [];
    const state = { current: notice };
    const { TelemetryNoticeController } = await loadModule(new URL("./TelemetryNoticeController.jsx", import.meta.url), runtime, {
        "@logics_configs": { useOthers: () => ({
            currentTelemetryNotice: state.current,
            setTelemetryNotice: async value => { sent.push(value); },
            getTelemetry: () => refreshed.push(true),
        }) },
        "../../../logics/common/useConsentDialog": { useConsentDialog: open => ({ dialog: { current: null, open } }) },
        "../config_page/setting_section/setting_box/_components/telemetry/TelemetryContents": { TelemetryContents },
    });
    context.after(() => runtime.unmount());
    const render = () => runtime.render(TelemetryNoticeController);
    const buttons = () => {
        const found = [];
        find(render(), node => { if (node.type === "button") found.push(node); return false; });
        return found;
    };
    return { render, buttons, sent, refreshed, state };
}

test("the notice is asked only while the backend says it is pending", async context => {
    for (const notice of [
        { state: "ok", data: { pending: false, enabled: true } },
        // Not known yet, or a write under way: no dialog is shown on a guess.
        { state: "pending", data: { pending: true, enabled: true } },
        { state: "ok", data: null },
    ]) {
        const s = await setup(context, notice);
        assert.equal(s.render(), null);
    }
    const s = await setup(context, { state: "ok", data: { pending: true, enabled: true } });
    const dialog = find(s.render(), node => node.type === "dialog");
    assert.equal(dialog.props["aria-label"], "telemetry_notice.title");
    const texts = [];
    find(dialog, node => { if (node.type === "p") texts.push(node.props.children); return false; });
    // What is sent, what is not, and where to change it.
    assert.deepEqual(texts, ["telemetry_notice.what", "telemetry_notice.not_sent", "telemetry_notice.change"]);
    // The event itself can be read before choosing; in the notice, without a list of what was sent.
    const contents = find(dialog, node => node.type === TelemetryContents);
    assert.ok(contents);
    assert.equal(contents.props.with_sent, undefined);
    assert.deepEqual(s.buttons().map(button => button.props.children), ["telemetry_notice.send", "telemetry_notice.dont_send"]);
});

test("each answer is sent once, and Escape does not answer for the user", async context => {
    for (const [index, send] of [[0, true], [1, false]]) {
        const s = await setup(context, { state: "ok", data: { pending: true, enabled: true } });
        // Escape (the dialog's cancel) is refused: the notice stays until one of the two is chosen.
        let prevented = false;
        find(s.render(), node => node.type === "dialog").props.onCancel({ preventDefault: () => { prevented = true; } });
        assert.equal(prevented, true);
        assert.deepEqual(s.sent, []);
        await s.buttons()[index].props.onClick();
        assert.deepEqual(s.sent, [{ send }]);
        // The switch in the settings is asked to show the same choice.
        assert.deepEqual(s.refreshed, [true]);
        // A second press while the first is on its way does nothing.
        assert.equal(s.buttons().every(button => button.props.disabled === true), true);
        await s.buttons()[index].props.onClick();
        assert.deepEqual(s.sent, [{ send }]);
    }
});
