import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../../logics/test/hookHarness.js";

async function setup() {
    const runtime = hooks(), saves = [];
    const Entry = () => null;
    const { HotkeysEntry } = await loadModule(new URL("./HotkeysEntry.jsx", import.meta.url), runtime, {
        "../_atoms/_entry/_Entry": { _Entry: Entry },
    });
    const props = { value: { open_quick_chat: ["Ctrl", "Q"] }, hotkey_id: "open_quick_chat", label: "クイックチャット",
        setHotkeys: async value => { saves.push(value); return true; } };
    let current;
    const render = () => {
        const tree = runtime.render(HotkeysEntry, props, tree => {
            current = find(tree, node => node.type === Entry);
            current.ref.current = { blur: () => current.props.onBlur() };
        });
        return tree;
    };
    const field = () => { render(); return current.props; };
    const key = (name, extra = {}) => {
        const event = { key: name, defaultPrevented: false, stopped: false,
            preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...extra };
        field().onKeyDown(event);
        field().onKeyUp(event);
        return event;
    };
    field();
    field().onFocus();
    return { render, field, key, saves };
}

for (const shiftKey of [false, true]) test(`${shiftKey ? "Shift+Tab" : "Tab"} moves focus without saving a binding`, async () => {
    const subject = await setup();
    if (shiftKey) subject.field().onKeyDown({ key: "Shift", shiftKey: true, preventDefault() {} });
    const event = subject.key("Tab", { shiftKey });
    assert.equal(event.defaultPrevented, false);
    subject.field().onBlur();
    subject.field().onKeyUp({ key: "Shift" });
    assert.deepEqual(subject.saves, []);
    assert.equal(subject.field().ui_variable, "Ctrl + Q");
    assert.equal(subject.field()["aria-label"], "クイックチャット");
});

test("Escape cancels an unfinished chord and restores the acknowledged binding without saving", async () => {
    const subject = await setup();
    subject.field().onKeyDown({ key: "w", ctrlKey: true, preventDefault() {} });
    assert.equal(subject.field().ui_variable, "Ctrl + W");
    const event = subject.key("Escape");
    assert.equal(event.defaultPrevented, true);
    assert.equal(event.stopped, true);
    subject.field().onKeyUp({ key: "w" });
    assert.deepEqual(subject.saves, []);
    assert.equal(subject.field().ui_variable, "Ctrl + Q");
    subject.key("n", { ctrlKey: true });
    assert.deepEqual(subject.saves, [{ open_quick_chat: ["Ctrl", "N"] }]);
});

test("blur cancels a partial chord; a fresh chord and the clear button still save", async () => {
    const subject = await setup();
    subject.field().onKeyDown({ key: "w", ctrlKey: true, preventDefault() {} });
    subject.field().onBlur();
    subject.field().onKeyUp({ key: "w" });
    assert.deepEqual(subject.saves, []);
    subject.field().onFocus();
    subject.key("w", { ctrlKey: true });
    assert.deepEqual(subject.saves, [{ open_quick_chat: ["Ctrl", "W"] }]);
    const clear = find(subject.render(), node => node.type === "button");
    assert.equal(clear.props["aria-label"], "quick_chat.clear_shortcut");
    clear.props.onClick();
    assert.deepEqual(subject.saves.at(-1), { open_quick_chat: null });
});
