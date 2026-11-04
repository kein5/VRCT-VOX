import assert from "node:assert/strict";
import { test } from "node:test";
import clsx from "clsx";
import { hooks, loadModule, find, stubGlobals, eventTarget } from "../../../../../../logics/test/hookHarness.js";

const all = (tree, predicate) => {
    const nodes = [];
    find(tree, node => { if (predicate(node)) nodes.push(node); return false; });
    return nodes;
};
const key = name => ({ key: name, nativeEvent: {}, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });
const focusNode = document => ({ focus() { document.activeElement = this; }, blur() { document.activeElement = document.body; } });

for (const index of [0, 1, 2]) test(`word filter names its delete buttons and focuses a neighbour after deleting index ${index}`, async t => {
    const runtime = hooks(), document = { body: {}, activeElement: null };
    stubGlobals(t, { document, requestAnimationFrame: fn => fn() });
    const state = { currentMicWordFilterList: { data: ["alpha", "日本語", "gamma"] },
        updateMicWordFilterList(fn) { this.currentMicWordFilterList.data = fn(this.currentMicWordFilterList); },
        setMicWordFilterList: () => {} };
    // The production hook's functions are destructured, so the fake uses closures too.
    state.updateMicWordFilterList = fn => { state.currentMicWordFilterList.data = fn(state.currentMicWordFilterList); };
    const Entry = () => null;
    const { WordFilter } = await loadModule(new URL("./word_filter/WordFilter.jsx", import.meta.url), runtime, {
        "@logics_configs": { useTranscription: () => state },
        "@store": { useStore_IsOpenedMicWordFilterList: () => ({ currentIsOpenedMicWordFilterList: { data: true } }) },
        "@useI18n": { useI18n: () => ({ t: (name, values) => values?.word ? `Remove ${values.word}` : name }) },
        "../_atoms/_entry/_Entry": { _Entry: Entry },
    });
    const buttons = new Map(), entryNode = focusNode(document);
    let rows;
    const render = () => runtime.render(WordFilter, {}, tree => {
        find(tree, node => node.type === Entry).ref.current = entryNode;
        rows = all(tree, node => node.props?.deleteAction).map(row => {
            const rendered = row.type(row.props);
            const button = find(rendered, node => node.type === "button");
            const node = buttons.get(row.key) ?? focusNode(document);
            buttons.set(row.key, node);
            button.ref(node);
            return { word: row.props.value, key: row.key, button, node, rendered };
        });
    });
    render();
    const original = rows.slice();
    for (const row of rows) {
        assert.equal(row.key, `.$${row.word}`);
        assert.equal(row.button.props["aria-label"], `Remove ${row.word}`);
        assert.equal(row.button.props.children.props["aria-hidden"], "true");
        assert.equal(row.button.props.children.props.focusable, "false");
    }
    const remove = row => {
        row.node.focus();
        row.button.props.onClick({ currentTarget: row.node });
        document.activeElement = document.body; // Native removal of the focused button.
        render();
    };
    remove(rows[index]);
    assert.equal(document.activeElement, original[index === 2 ? 1 : index + 1].node);
    while (rows.length) remove(rows[0]);
    assert.equal(document.activeElement, entryNode);
});

test("checkbox input stays mounted and focused through pending, including rejection", async t => {
    const runtime = hooks(), document = { body: {} };
    stubGlobals(t, { document });
    const { Checkbox } = await loadModule(new URL("../../../../../common_components/checkbox/Checkbox.jsx", import.meta.url), runtime);
    let toggles = 0;
    const props = { label: "Show resend button", variable: { state: "ok", data: false }, toggleFunction: () => toggles++ };
    const render = () => runtime.render(Checkbox, props);
    const original = find(render(), node => node.type === "input");
    const focused = focusNode(document); focused.focus();
    original.props.onChange();
    assert.equal(toggles, 1);
    for (const state of ["pending", "ok"]) {
        props.variable.state = state;
        const tree = render(), input = find(tree, node => node.type === "input");
        assert.equal(input.type, original.type);
        assert.equal(input.key, original.key);
        assert.notEqual(input.props.disabled, true);
        assert.equal(input.props["aria-busy"], state === "pending");
        assert.equal(input.props["aria-disabled"], state === "pending");
        // The input remains in the same child slot, immediately before its focus drawing.
        const label = find(tree, node => node.type === "label");
        assert.equal(label.props.children[0].props, input.props);
        assert.equal(label.props.children[1].props.className, "cbx");
        assert.equal(document.activeElement, focused);
        if (state === "pending") {
            input.props.onChange();
            const click = key(); input.props.onClick(click);
            const space = key(" "); input.props.onKeyDown(space);
            assert.equal(click.defaultPrevented, true);
            assert.equal(space.defaultPrevented, true);
            assert.equal(toggles, 1);
            assert.equal(label.props.children[2].props["aria-hidden"], "true");
        }
    }
});

for (const label of ["WebSocket locked by OBS", "Mic mute sync without OSC", "OCR detector not installed"]) {
    test(`unavailable checkbox ignores click, Space and change: ${label}`, async () => {
        const runtime = hooks();
        const { Checkbox } = await loadModule(new URL("../../../../../common_components/checkbox/Checkbox.jsx", import.meta.url), runtime);
        let calls = 0;
        const tree = runtime.render(Checkbox, { label, variable: { state: "ok", data: false }, is_available: false,
            "aria-describedby": "warning", toggleFunction: () => calls++ });
        const input = find(tree, node => node.type === "input");
        assert.equal(input.props["aria-disabled"], true);
        assert.equal(input.props["aria-describedby"], "warning");
        for (const [handler, name] of [["onClick", undefined], ["onKeyDown", " "], ["onKeyDown", "Enter"]]) {
            const event = key(name); input.props[handler](event); assert.equal(event.defaultPrevented, true);
        }
        input.props.onChange();
        assert.equal(calls, 0);
    });
}

for (const [name, path] of [["EntryWithSaveButton", "entry_with_save_button"], ["AuthKey", "auth_key"], ["ColorEntryWithSaveButton", "color_entry_with_save_button"]]) {
    test(`${name} Enter saves once, keeps focus and guards pending editing`, async t => {
        const runtime = hooks(), inputRuntime = hooks(), document = { ...eventTarget(), body: {} };
        stubGlobals(t, { document, window: eventTarget() });
        inputRuntime.api.useImperativeHandle = () => {};
        const { _Entry } = await loadModule(new URL("./_atoms/_entry/_Entry.jsx", import.meta.url), inputRuntime);
        const { [name]: Component } = await loadModule(new URL(`./${path}/${name}.jsx`, import.meta.url), runtime, {
            clsx: { clsx }, "../_atoms/_entry/_Entry": { _Entry }, "react-colorful": { HexColorPicker: () => null },
        });
        let saves = 0, edits = 0;
        const props = { label: "Field", variable: "", state: "ok", "aria-describedby": "help",
            saveFunction: () => saves++, onChangeFunction: () => edits++ };
        const node = focusNode(document); node.focus();
        const render = () => {
            const entry = find(runtime.render(Component, props), item => item.type === _Entry);
            if (entry.ref) entry.ref.current = node;
            return find(inputRuntime.render(p => _Entry.render(p, null), entry.props), item => item.type === "input");
        };
        let input = render();
        input.props.onKeyDown({ ...key("Enter"), target: node });
        assert.equal(saves, 1);
        assert.equal(document.activeElement, node);
        props.state = "pending";
        input = render();
        assert.equal(input.props.disabled, false);
        assert.equal(input.props.readOnly, true);
        assert.equal(input.props["aria-busy"], true);
        assert.equal(input.props["aria-describedby"], "help");
        input.props.onKeyDown({ ...key("Enter"), target: node });
        input.props.onChange({ target: { value: "changed" } });
        assert.equal(saves, 1); assert.equal(edits, 0);
        assert.equal(document.activeElement, node);
        const elsewhere = focusNode(document); elsewhere.focus();
        props.state = "ok"; render();
        assert.equal(document.activeElement, elsewhere);
        runtime.unmount();
    });
}

test("threshold Enter commits without blur or a duplicate blur-triggered save", async t => {
    const runtime = hooks(), saves = [], document = { body: {} };
    stubGlobals(t, { document });
    const Entry = () => null;
    const { ThresholdEntry } = await loadModule(new URL("./threshold_component/threshold_entry/ThresholdEntry.jsx", import.meta.url), runtime, {
        "../../_atoms/_entry/_Entry": { _Entry: Entry },
    });
    const wrapper = ThresholdEntry({ ui_threshold: 120, setThresholdFunction: value => saves.push(value) });
    const input = runtime.render(wrapper.type, wrapper.props);
    const node = focusNode(document); node.focus();
    input.props.onEnterPressed({ target: node });
    assert.equal(document.activeElement, node);
    assert.deepEqual(saves, ["120"]);
    runtime.unmount();
});

test("_Entry forwards ARIA relations and Enter ignores IME confirmation", async () => {
    const runtime = hooks(); runtime.api.useImperativeHandle = () => {};
    const { _Entry } = await loadModule(new URL("./_atoms/_entry/_Entry.jsx", import.meta.url), runtime);
    const aria = { "aria-label": "Name", "aria-labelledby": "label", "aria-describedby": "help error",
        "aria-invalid": true, "aria-busy": true, "aria-disabled": true, "aria-controls": "popup", "aria-expanded": false };
    let saves = 0;
    const input = find(runtime.render(props => _Entry.render(props, null), { ...aria, onEnterPressed: () => saves++ }), node => node.type === "input");
    for (const [name, value] of Object.entries(aria)) assert.equal(input.props[name], value);
    input.props.onKeyDown({ ...key("Enter"), nativeEvent: { isComposing: true } });
    input.props.onKeyDown({ ...key("Enter"), keyCode: 229 });
    assert.equal(saves, 0);
});
