import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, eventTarget } from "../test/hookHarness.js";

const componentRoot = "../../views/app/config_page/setting_section/setting_box/_components/";
const pointer = (x, y = 0) => ({ button: 0, clientX: x, clientY: y, preventDefault() {} });
const track = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }) };

test("slider installs listeners once per drag, reads current values/callbacks and cleans up", async t => {
    const runtime = hooks(), window = eventTarget(), changed = [], committed = [];
    globalThis.window = window;
    t.after(() => { runtime.unmount(); delete globalThis.window; });
    let version = 0, value = 0;
    const { Slider } = await loadModule(new URL(`${componentRoot}slider/Slider.jsx`, import.meta.url), runtime, {
        "@logics_configs": { useSliderLogic: () => {
            const current = version;
            return { ui_value: value, onChangeFunction: next => { value = next; changed.push([current, next]); },
                onChangeCommittedFunction: next => committed.push([current, next]) };
        } },
    });
    const props = { min: 0, max: 100, step: 1 };
    const render = () => runtime.render(Slider, props, tree => {
        find(tree, node => node.props?.onPointerDown).ref.current = track;
    });
    const start = () => find(render(), node => node.props?.onPointerDown).props.onPointerDown(pointer(10));
    start(); render();
    const installed = [...window.added];
    assert.deepEqual(installed.map(([type]) => type), ["pointermove", "pointerup"]);
    for (const x of [20, 30, 40]) {
        version++;
        render();
        window.dispatch("pointermove", pointer(x));
        render();
    }
    assert.deepEqual(changed, [[0, 10], [1, 20], [2, 30], [3, 40]]);
    window.dispatch("pointermove", pointer(40));
    assert.equal(changed.length, 4); // Compares with the latest ui_value.
    props.max = 200; props.orientation = "vertical"; version++;
    render();
    window.dispatch("pointerup", pointer(0, 25));
    render();
    assert.deepEqual(committed, [[4, 150]]);
    assert.deepEqual(window.added, installed);
    assert.deepEqual(window.removed, installed);
    start(); render();
    assert.equal(window.added.length, 4);
    runtime.unmount();
    assert.deepEqual(window.removed, window.added);
    window.dispatch("pointerup", pointer(0));
    assert.equal(committed.length, 1);
});

for (const timing of ["on_change", "on_change_committed"]) test(`slider retains production ${timing} debounce/commit behavior`, async t => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), window = eventTarget(), sent = [];
    globalThis.window = window;
    t.after(() => { runtime.unmount(); delete globalThis.window; });
    const settings = await loadModule(new URL("../configs/config_page_setter/useSettingsLogics.js", import.meta.url), runtime, {
        "@store": {}, "@logics_common": {}, "@utils": {}, "../../voice/saveBar": {},
    });
    const { Slider } = await loadModule(new URL(`${componentRoot}slider/Slider.jsx`, import.meta.url), runtime, {
        "@logics_configs": settings,
    });
    const props = { min: 0, max: 100, step: 1, variable: 0, state: "ok", setter_timing: timing,
        setterFunction: value => { sent.push(value); return true; } };
    const render = () => runtime.render(Slider, props, tree => { find(tree, node => node.props?.onPointerDown).ref.current = track; });
    find(render(), node => node.props?.onPointerDown).props.onPointerDown(pointer(10));
    render();
    window.dispatch("pointermove", pointer(20)); render();
    t.mock.timers.tick(100);
    window.dispatch("pointermove", pointer(30)); render();
    t.mock.timers.tick(199);
    assert.deepEqual(sent, []);
    window.dispatch("pointerup", pointer(30)); render();
    if (timing === "on_change") {
        assert.deepEqual(sent, []);
        t.mock.timers.tick(1);
    }
    assert.deepEqual(sent, [30]);
    assert.deepEqual(window.added.map(([type]) => type), ["pointermove", "pointerup"]);
    assert.deepEqual(window.removed, window.added);
    find(render(), node => node.props?.onPointerDown).props.onPointerDown(pointer(40)); render();
    runtime.unmount();
    t.mock.timers.tick(1000);
    assert.deepEqual(sent, [30]);
    assert.deepEqual(window.removed, window.added);
});

test("dropdown keeps open listeners through renders, uses the latest updater and cleans up", async t => {
    const runtime = hooks(), document = eventTarget(), window = { ...eventTarget(), innerHeight: 800 }, updates = [];
    globalThis.document = document; globalThis.window = window;
    t.after(() => { runtime.unmount(); delete globalThis.document; delete globalThis.window; });
    let opened = "", version = 0;
    const { _DropdownMenu } = await loadModule(new URL(`${componentRoot}_atoms/_dropdown_menu/_DropdownMenu.jsx`, import.meta.url), runtime, {
        "@store": { useStore_IsOpenedDropdownMenu: () => {
            const current = version++;
            return { currentIsOpenedDropdownMenu: { data: opened },
                updateIsOpenedDropdownMenu: value => { opened = value; updates.push([current, value]); } };
        } },
    });
    const props = { dropdown_id: "test", state: "ok", list: { one: "One", two: "Two" }, selected_id: "one", selectFunction() {} };
    const inside = {}, container = { contains: target => target === inside,
        getBoundingClientRect: () => ({ top: 200, bottom: 240 }) };
    const render = () => runtime.render(_DropdownMenu, props, tree => {
        tree.ref.current = container;
        find(tree, node => node.props?.role === "listbox").ref.current = { offsetHeight: 200, children: [] };
    });
    find(render(), node => node.props?.role === "combobox").props.onClick();
    render();
    const installed = [...document.added];
    assert.deepEqual(installed.map(([type]) => type), ["pointerdown", "keydown"]);
    for (let i = 0; i < 4; i++) render();
    const latest = version - 1;
    document.dispatch("pointerdown", { target: inside });
    document.dispatch("keydown", { key: "Enter" });
    assert.equal(opened, "test");
    document.dispatch("keydown", { key: "Escape" });
    assert.deepEqual(updates.at(-1), [latest, ""]);
    render();
    assert.deepEqual(document.added, installed);
    assert.deepEqual(document.removed, installed);
    assert.deepEqual(window.removed, window.added);
    find(render(), node => node.props?.role === "combobox").props.onClick(); render(); render();
    document.dispatch("pointerdown", { target: {} });
    assert.deepEqual(updates.at(-1), [version - 1, ""]);
    runtime.unmount();
    assert.deepEqual(document.removed, document.added);
    assert.deepEqual(window.removed, window.added);
});
