import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals, eventTarget } from "../../../../../../logics/test/hookHarness.js";
import { rebaseDraft } from "../../../../../../logics/voice/draftRebase.js";
import { changedPaths } from "../../../../../../logics/voice/saveBar.js";

const draftPath = "../../../../../../logics/voice/useSettingsDraft.jsx";
const importsPath = "../../../../../../../logics/voice/useSettingsDraft";
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

async function setup(context, kind) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), requests = [];
    context.after(() => runtime.unmount());
    stubGlobals(context, { window: eventTarget(), document: { body: {} }, requestAnimationFrame: fn => fn() });
    let entry;
    const { useSettingsDraft } = await loadModule(new URL(draftPath, import.meta.url), runtime, {
        "./draftRebase": { rebaseDraft }, "./saveBar": { changedPaths, setSaveBarEntry: (_id, value) => { entry = value; } },
    });
    const defaults = { message: { prefix: "", suffix: "" }, translation: { prefix: "(", suffix: ")", separator: "/" }, separator: " ", translation_first: false };
    const saved = { state: "ok", data: kind === "word" ? ["old"] : structuredClone(defaults) };
    const send = value => new Promise(resolve => { saved.state = "pending"; requests.push({ value, resolve }); });
    const Entry = () => null;
    const common = { [importsPath]: { useSettingsDraft }, "../_atoms/_entry/_Entry": { _Entry: Entry } };
    let Component, props;
    if (kind === "word") {
        const state = { currentMicWordFilterList: saved, setMicWordFilterList: send,
            updateMicWordFilterList: fn => { saved.data = fn(saved); saved.state = "ok"; } };
        ({ WordFilter: Component } = await loadModule(new URL("./word_filter/WordFilter.jsx", import.meta.url), runtime, {
            ...common, "@logics_configs": { useTranscription: () => state },
            "@store": { useStore_IsOpenedMicWordFilterList: () => ({ currentIsOpenedMicWordFilterList: { data: true }, updateIsOpenedMicWordFilterList() {} }) },
        }));
        props = {};
    } else {
        ({ MessageFormat: Component } = await loadModule(new URL("./message_format/MessageFormat.jsx", import.meta.url), runtime, {
            ...common, "react-i18next": { useTranslation: () => ({ t: key => key }) },
            "@store": { useStore_IsBreakPoint: () => ({ currentIsBreakPoint: { data: false } }) },
            "@logics_configs": {}, "@common_components": { ResetButton: "reset" },
            "@ui_configs": { ui_configs: { send_message_format_parts: defaults, received_message_format_parts: defaults } },
        }));
        props = { variable: saved, setFunction: send, format_id: "send", label: "Send format" };
    }
    const render = () => { runtime.render(Component, props); return runtime.render(Component, props); };
    // InputComponent is intentionally private; exercise the component rendered by the parent.
    const input = () => {
        const node = find(render(), node => node.type?.name === "InputComponent");
        return node ? node.type(node.props) : null;
    };
    const reject = async () => {
        saved.state = "ok";
        requests.at(-1).resolve(false); await flush(); render();
    };
    render();
    return { render, input, Entry, requests, saved, defaults, reject, get entry() { return entry; } };
}

test("word filter stages additions and deletions without changing confirmed data, and retains rejected edits", async context => {
    const s = await setup(context, "word");
    find(s.render(), node => node.type === s.Entry).props.onChange({ target: { value: "new" } });
    find(s.render(), node => node.type === s.Entry).props.onEnterPressed();
    s.render();
    assert.deepEqual(s.saved.data, ["old"]);
    assert.equal(s.requests.length, 0);
    assert.equal(s.entry.edited, true);
    const saving = s.entry.save(); s.render();
    assert.equal(s.saved.state, "pending");
    assert.deepEqual(s.requests[0].value, ["old", "new"]);
    await s.reject(); await saving;
    assert.equal(s.entry.saveState, "save_failed");
    assert.ok(find(s.render(), node => node.props?.value === "new"));
    s.entry.discard(); s.render();
    const row = find(s.render(), node => node.props?.value === "old");
    row.props.deleteAction("old", {}); s.render();
    const removal = s.entry.save(); s.render();
    assert.deepEqual(s.requests.at(-1).value, []);
    await s.reject(); await removal;
    assert.deepEqual(s.saved.data, ["old"]);
    assert.equal(s.entry.saveState, "save_failed");
});

for (const action of ["reset", "swap"]) test(`message format ${action} shares the draft and cannot be undone by a stale timer`, async context => {
    const s = await setup(context, "message");
    const prefix = () => find(s.input(), node => node.props?.["aria-label"]?.endsWith("before_original"));
    prefix().props.onChange({ target: { value: "draft" } }); s.render();
    assert.equal(s.entry?.edited, true);
    assert.equal(s.requests.length, 0);
    const leave = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, detail: { proceed() {} } };
    window.dispatch("vrct:settings-leave", leave);
    assert.equal(leave.defaultPrevented, true);
    if (action === "reset") find(s.input(), node => node.type === "reset").props.onClickFunction();
    else find(s.input(), node => node.props?.className === "swap_button_wrapper").props.onClick();
    s.render(); context.mock.timers.tick(600); s.render();
    assert.equal(s.requests.length, 0);
    assert.equal(prefix().props.ui_variable, action === "reset" ? "" : "draft");
    if (action === "reset") prefix().props.onChange({ target: { value: "retry" } });
    s.render();
    prefix().props.onEnterPressed(); s.render();
    assert.equal(s.requests.length, 1);
    assert.equal(s.requests[0].value.translation_first, action === "swap");
    await s.reject();
    assert.equal(s.entry.saveState, "save_failed");
    assert.equal(prefix().props.ui_variable, action === "reset" ? "retry" : "draft");
    s.entry.discard(); s.render();
    assert.equal(prefix().props.ui_variable, "");
});
