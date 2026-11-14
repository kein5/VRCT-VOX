import assert from "node:assert/strict";
import * as featureLabel from "../../logics/common/featureLabel.js";
import { test } from "node:test";
import React from "react";
import { hooks, loadModule, find, stubGlobals, eventTarget } from "../../logics/test/hookHarness.js";
import * as languageNames from "../../logics/common/languageNames.js";
import { languageCodes } from "../../logics/common/languageCodes.js";
import { languageJumpGroups } from "../../logics/common/languageJumpGroups.js";
import { trackVrPointerHover } from "./vrPanelHover.js";

const fonts = Array.from({ length: 743 }, (_, index) => ({ id: `font-${index}`, label: `Font ${index}` }));
const languages = Object.entries(languageCodes).flatMap(([language, countries]) =>
    Object.keys(countries).map(country => ({ language, country })));
const all = (tree, predicate) => {
    if (!tree || typeof tree !== "object") return [];
    return [...(predicate(tree) ? [tree] : []), ...React.Children.toArray(tree.props?.children).flatMap(child => all(child, predicate))];
};

// Like the LogBox harness, exercise production JSX with a lazy Virtualizer
// stub. This models a 320px viewport, 80px rows and virtua's default 200px
// buffer, not WebView layout/performance. No browser/app is started.
async function pickerHarness(context, { height = 320, margin = 89, scale = 1 } = {}) {
    const runtime = hooks(), calls = [], landed = [], observers = [], nodes = new Map(), frames = new Map();
    // Replay effect cleanup/setup with state and refs intact, as StrictMode
    // does. Keep this local to the picker harness; other hook tests need no replay.
    const layoutEffects = new Map(), useLayoutEffect = runtime.api.useLayoutEffect;
    let layoutIndex = 0;
    runtime.api.useLayoutEffect = (setup, deps) => {
        const index = layoutIndex++;
        useLayoutEffect(() => {
            const effect = { setup, cleanup: setup() };
            layoutEffects.set(index, effect);
            return () => { effect.cleanup?.(); layoutEffects.delete(index); };
        }, deps);
    };
    let sequence = 0;
    let tree, rowTrees = [], virtualProps, props, measures = 0;
    const scroll = { scrollTop: 0, clientHeight: height,
        getBoundingClientRect: () => ({ top: 0, bottom: height * scale, height: height * scale }) };
    const header = { previousElementSibling: null };
    const container = { previousElementSibling: header,
        getBoundingClientRect: () => { measures++; return { top: (margin - scroll.scrollTop) * scale }; } };
    const document = { activeElement: { closest: () => null } };
    stubGlobals(context, { document,
        getComputedStyle: node => ({ visibility: node.hidden ? "hidden" : "visible" }),
        requestAnimationFrame: callback => { frames.set(++sequence, callback); return sequence; },
        cancelAnimationFrame: id => frames.delete(id),
        ResizeObserver: class {
        constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
        observe(element) { this.observed.push(element); }
        disconnect() { this.disconnected = true; }
    } });
    // virtua 0.53.5 queues attachment for scrollRef. A scroll awaits the
    // current deferred; cleanup resolves it false and creates the next one.
    const deferred = () => {
        let resolve;
        const promise = new Promise(done => { resolve = done; });
        return { promise, resolve };
    };
    let attachment = deferred(), virtualMounted = false, virtualRef;
    const mountVirtualizer = () => {
        virtualMounted = true;
        virtualRef.current = handle;
        queueMicrotask(() => { if (props.scrollRef.current) attachment.resolve(true); });
    };
    const cleanupVirtualizer = () => {
        if (!virtualMounted) return;
        attachment.resolve(false);
        attachment = deferred();
        virtualMounted = false;
        virtualRef.current = null;
    };
    const handle = { scrollToIndex: async (index, options) => {
        calls.push([index, options]);
        if (!await attachment.promise) return;
        const total = virtualProps.data.length * virtualProps.itemSize;
        scroll.scrollTop = Math.max(0, Math.min(total + margin - height, margin + index * virtualProps.itemSize + options.offset));
        landed.push(index);
    } };
    const Virtualizer = () => null;
    const module = await loadModule(new URL("./VrPickerList.jsx", import.meta.url), runtime, { virtua: { Virtualizer } });
    const navigationRef = { current: null }, scrollRef = { current: scroll };
    const render = (next = props) => {
        props = { scrollRef, navigationRef, ...next };
        props.scrollRef.current = scroll;
        layoutIndex = 0;
        tree = runtime.render(module.VrPickerList, props, root => {
            root.ref.current = container;
            const virtual = find(root, node => node.type === Virtualizer);
            if (virtual) {
                virtualProps = virtual.props;
                virtualRef = virtual.ref;
                if (!virtualMounted) mountVirtualizer();
                const { data, itemSize, bufferSize = 200, keepMounted = [] } = virtual.props;
                const from = Math.max(0, Math.floor((scroll.scrollTop - margin - bufferSize) / itemSize));
                const to = Math.min(data.length - 1, Math.floor((scroll.scrollTop + height - margin + bufferSize) / itemSize));
                const indices = new Set(keepMounted);
                for (let i = from; i <= to; i++) indices.add(i);
                rowTrees = [...indices].sort((a, b) => a - b).map(index => virtual.props.children(data[index], index));
            } else {
                cleanupVirtualizer();
                virtualProps = undefined;
                rowTrees = React.Children.toArray(root.props.children);
            }
            const rendered = rowTrees.flatMap(row => all(row, node => node.type === "button"));
            for (const node of nodes.values()) node.element.ref(null);
            const old = new Map(nodes);
            nodes.clear();
            for (const element of rendered) {
                const index = element.props["data-vr-picker-index"];
                const node = old.get(index) ?? { dataset: { vrPickerIndex: String(index) },
                    closest: selector => selector === "[data-vr-picker-index]" ? node : selector === ".picker_scroll" ? scroll : null,
                    matches: selector => selector === ":disabled" && !!node.element.props.disabled,
                    focus: () => {
                        if (node.element.props.disabled || node.hidden) return;
                        document.activeElement = node;
                        root.props.onFocusCapture({ target: node });
                    },
                    getBoundingClientRect: () => {
                        const top = (margin + Math.floor(index / (props.columns ?? 1)) * 80 - scroll.scrollTop) * scale;
                        return { top, bottom: top + 72 * scale };
                    },
                };
                node.element = element;
                nodes.set(index, node);
                element.ref(node);
            }
        });
        return tree;
    };
    const frame = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); };
    const microtasks = () => new Promise(resolve => queueMicrotask(resolve));
    const settle = async next => {
        render(next); await microtasks(); frame();
        render(); await microtasks(); frame();
        render(); await microtasks();
    };
    const replayMountEffects = ({ picker = true } = {}) => {
        cleanupVirtualizer();
        if (picker) layoutEffects.forEach(effect => effect.cleanup?.());
        mountVirtualizer();
        if (picker) layoutEffects.forEach(effect => { effect.cleanup = effect.setup(); });
    };
    const unmount = runtime.unmount;
    runtime.unmount = () => {
        cleanupVirtualizer();
        unmount();
        if (props) props.scrollRef.current = null;
    };
    context.after(() => runtime.unmount());
    return { ...module, runtime, render, settle, replayMountEffects, microtasks, landed, frame, frames, navigationRef, scrollRef, scroll, calls, nodes, observers, document,
        get tree() { return tree; }, get virtualProps() { return virtualProps; },
        get rowCount() { return rowTrees.length; }, get measures() { return measures; },
    };
}

async function fontPicker(context, selected_id = "font-0", layout) {
    const h = await pickerHarness(context, layout), picked = [];
    const { Picker } = await loadModule(new URL("./VrSettingsRows.jsx", import.meta.url), hooks(), {
        "./VrPickerList": { VrPickerList: h.VrPickerList },
    });
    const tree = Picker({ title: "Fonts", back_label: "Back", options: fonts, selected_id,
        scrollRef: h.scrollRef, onPick: value => picked.push(value) });
    await h.settle(find(tree, node => node.type === h.VrPickerList).props);
    return { h, picked };
}

for (const picker of [false, true]) {
    test(`initial font positioning survives StrictMode ${picker ? "whole-picker" : "Virtualizer-only"} effect replay`, async context => {
        const h = await pickerHarness(context);
        h.render({ options: fonts.slice(0, 316), initialIndex: 287, stickyHeader: true,
            children: option => React.createElement("button", { key: option.id }, option.label) });
        h.render(); // The measured prefix mounts virtua and runs the init effect.
        h.replayMountEffects({ picker }); // Cleanup precedes both attachment microtasks.
        await h.settle();
        assert.equal(h.scroll.scrollTop, 22960, "selected font lands below the sticky header");
        assert.ok(h.nodes.has(287));
        assert.equal(h.calls.length, 1, "only one initial positioning request per open");
        assert.deepEqual(h.landed, [287]);
        h.scroll.scrollTop = 1024;
        await h.settle();
        assert.equal(h.scroll.scrollTop, 1024, "unrelated renders do not restore the initial position");
        assert.equal(h.calls.length, 1);
        // Real input occurs after the commit and its microtasks. Both operations
        // must scroll through the current attachment rather than a disposed one.
        h.navigationRef.current.scrollToIndex(290, { focus: true });
        await h.settle();
        assert.equal(h.scroll.scrollTop, 23200);
        h.tree.props.onKeyDown({ key: "Tab", target: h.nodes.get(290), preventDefault() {} });
        await h.settle();
        assert.equal(h.scroll.scrollTop, 23280);
        assert.equal(h.document.activeElement, h.nodes.get(291));
        assert.deepEqual(h.landed, [287, 290, 291]);
    });
}

test("closing before initial positioning cancels its microtask", async context => {
    const h = await pickerHarness(context);
    h.render({ options: fonts, initialIndex: 287, stickyHeader: true,
        children: option => React.createElement("button", { key: option.id }, option.label) });
    h.render();
    h.runtime.unmount();
    h.scroll.scrollTop = 4096; // The old scroll container may already be reused.
    await h.microtasks();
    assert.equal(h.scroll.scrollTop, 4096);
    assert.equal(h.calls.length, 0);
    assert.deepEqual(h.landed, []);
});

test("743 fonts create bounded lazy rows; a far selected font scrolls on open and retains its value", async context => {
    const { h, picked } = await fontPicker(context, "font-700", { scale: 0.5 });
    assert.equal(h.virtualProps.data.length, 743);
    assert.ok(h.nodes.size <= 14);
    assert.deepEqual(h.calls, [[700, { align: "start", offset: -89, smooth: false }]]);
    const selected = h.nodes.get(700).element;
    assert.equal(selected.props["aria-pressed"], true);
    assert.match(selected.props.className, /is_selected/);
    assert.equal(h.nodes.get(700).getBoundingClientRect().top, 89 * 0.5);
    selected.props.onClick();
    assert.deepEqual(picked, ["font-700"]);
    const measurements = h.measures;
    h.render();
    assert.equal(h.measures, measurements, "unrelated renders do not measure or restart scrolling");
    assert.equal(h.calls.length, 1);
    assert.equal(h.observers.length, 1);
    h.runtime.unmount();
    assert.ok(h.observers.every(observer => observer.disconnected));
    context.diagnostic(`743 fonts, selected index 700, viewport 320px, row pitch 80px, buffer 200px: 743 -> ${h.nodes.size} option buttons (${h.rowCount} rows), including keyboard endpoints; simulated layout.`);
});

test("short lists render all options and scroll the selected entry without scrolling the window", async context => {
    const h = await pickerHarness(context, { scale: 0.5 });
    const options = fonts.slice(0, 12), selected = [];
    await h.settle({ options, initialIndex: 10, stickyHeader: true,
        children: option => React.createElement("button", { key: option.id, onClick: () => selected.push(option.id) }, option.label) });
    assert.equal(h.virtualProps, undefined);
    assert.equal(h.nodes.size, 12);
    assert.equal(h.scroll.scrollTop, 800);
    h.nodes.get(10).element.props.onClick();
    assert.deepEqual(selected, ["font-10"]);
});

test("Tab crosses unmounted rows, skips disabled entries and retains a focused row during scroll", async context => {
    const { h } = await fontPicker(context);
    h.nodes.get(0).focus();
    h.scroll.scrollTop = 40000;
    h.render();
    assert.ok(h.nodes.has(0));
    assert.ok(!h.nodes.has(1));
    let prevented = 0;
    h.tree.props.onKeyDown({ key: "Tab", target: h.nodes.get(0), preventDefault: () => prevented++ });
    await h.settle();
    assert.equal(h.document.activeElement, h.nodes.get(1));
    assert.equal(prevented, 1);
    assert.equal(h.calls.at(-1)[0], 1);
    h.tree.props.onKeyDown({ key: "Tab", shiftKey: true, target: h.nodes.get(1), preventDefault: () => prevented++ });
    await h.settle();
    assert.equal(h.document.activeElement, h.nodes.get(0));
    h.tree.props.onKeyDown({ key: "Tab", shiftKey: true, target: h.nodes.get(0), preventDefault: () => prevented++ });
    assert.equal(prevented, 2, "native Shift+Tab leaves the first option");
    h.navigationRef.current.scrollToIndex(700, { focus: true });
    await h.settle();
    h.scroll.scrollTop = 0;
    h.render();
    assert.ok(h.nodes.has(700), "focused option survives scroll away");
    assert.ok(h.nodes.size <= 14);
});

async function languageWindow(context, h, locale = "en") {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), sorts = [], filters = [], picked = [];
    const ok = data => ({ state: "ok", data });
    const source = languages[0];
    const target = languages.find(entry => entry.language === "Japanese");
    const settings = {
        currentSelectedPresetTabNumber: ok("1"),
        currentSelectedYourLanguages: ok({ 1: { 1: source } }),
        currentSelectedTargetLanguages: ok({ 1: { 1: { ...target, enable: true } } }),
        currentSelectedTranslationEngines: ok({ 1: "engine" }),
        currentTranslationEngines: ok([{ id: "engine", label: "Engine", is_available: true }]),
        currentSelectableLanguageList: ok(languages), currentLanguageMutation: ok({ inFlight: null, isResyncing: false }),
        setSelectedYourLanguages: entry => { picked.push(entry); return "request-1"; },
        setTargetLanguagesInOrder: entries => { picked.push(entries); return "request-2"; },
    };
    const i18n = { language: locale };
    const { VrLanguageWindow } = await loadModule(new URL("./VrLanguageWindow.jsx", import.meta.url), runtime, {
        "./VrWindow": { VrWindow: () => null },
        "./VrPickerList": { VrPickerList: h.VrPickerList, VR_PICKER_WINDOW_THRESHOLD: h.VR_PICKER_WINDOW_THRESHOLD },
        "@useI18n": { useI18n: () => ({ t: key => key, i18n }) },
        "@logics_main": { useLanguageSettings: () => settings },
        "@logics_common": { useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: false } }) },
        "../../logics/main/languageMutations": { LANGUAGE_RESPONSE_WAIT_MS: 30000 },
        "../../logics/common/languageJumpGroups.js": { languageJumpGroups },
        "../../logics/common/languageNames.js": { ...languageNames, createLanguageNames: locale => {
            const names = languageNames.createLanguageNames(locale);
            return { ...names, sorted: entries => { sorts.push(entries); return names.sorted(entries); },
                matches: (entry, query) => { filters.push(query); return names.matches(entry, query); } };
        } },
    });
    let tree;
    const render = () => {
        tree = runtime.render(VrLanguageWindow, {}, root => {
            const scroll = find(root, node => node.props.className === "picker_scroll");
            if (scroll) scroll.ref.current = h.scroll;
        });
        return tree;
    };
    render();
    const open = (kind = "source") => {
        find(tree, node => node.type === "button" && node.props.className.split(" ").includes(kind)).props.onClick();
        render();
        find(tree, node => node.type === "button" && node.props.className.includes("all_languages")).props.onClick();
        render();
    };
    context.after(() => runtime.unmount());
    return { render, open, settings, sorts, filters, picked, i18n, source,
        get tree() { return tree; }, get list() { return find(tree, node => node.type === h.VrPickerList); } };
}

test("the full language grid mounts bounded pairs and group jumps use the filtered option index", async context => {
    const h = await pickerHarness(context, { margin: 38 });
    const w = await languageWindow(context, h);
    w.open();
    await h.settle(w.list.props);
    assert.equal(w.list.props.options.length, 135);
    assert.equal(h.virtualProps.data.length, 68);
    assert.ok(h.nodes.size <= 28);
    context.diagnostic(`135 full language choices (languageCodes.js, English), selected first entry, viewport 320px, heading 38px, row pitch 80px, buffer 200px: 135 buttons / 68 rows -> ${h.nodes.size} buttons / ${h.rowCount} rows, including keyboard endpoints; simulated layout.`);
    const expected = w.list.props.options.findIndex(entry => entry.language === "Japanese");
    const jump = find(w.tree, node => node.props["data-vr-language-jump"] === "J");
    const choices = w.list.props.options;
    const groupIndex = languageJumpGroups(choices.map(entry => languageNames.createLanguageNames("en").name(entry).language), "en").find(group => group.id === "J").index;
    assert.equal(groupIndex, expected);
    assert.ok(!h.nodes.has(groupIndex));
    jump.props.onClick();
    await h.settle();
    assert.equal(h.calls.at(-1)[0], Math.floor(groupIndex / 2));
    assert.equal(h.document.activeElement, h.nodes.get(groupIndex));
    h.nodes.get(groupIndex).element.props.onClick();
    assert.strictEqual(w.picked[0], choices[groupIndex], "existing language setter receives the original entry");
    w.render();
    await h.settle(w.list.props);
    assert.equal(h.nodes.get(groupIndex).element.props["aria-disabled"], true);
    h.nodes.get(groupIndex).element.props.onClick();
    assert.equal(w.picked.length, 1, "pending choices cannot send another mutation");
});

test("initial language positioning and group jumps use the surviving StrictMode attachment", async context => {
    const h = await pickerHarness(context, { margin: 38 }), w = await languageWindow(context, h);
    const selected = languages.find(entry => entry.language === "Japanese");
    w.settings.currentSelectedYourLanguages = { state: "ok", data: { 1: { 1: selected } } };
    w.render();
    w.open();
    h.render(w.list.props);
    h.render();
    h.replayMountEffects();
    await h.settle();
    const index = w.list.props.options.indexOf(selected);
    assert.ok(h.scroll.scrollTop > 0);
    assert.ok(h.nodes.has(index));
    assert.equal(h.nodes.get(index).getBoundingClientRect().top, 0);
    assert.equal(h.calls.length, 1);
    assert.equal(h.landed.length, 1);
    find(w.tree, node => node.props["data-vr-language-jump"] === "A").props.onClick();
    await h.settle();
    assert.equal(h.scroll.scrollTop, 38);
    assert.equal(h.document.activeElement, h.nodes.get(0));
    assert.equal(h.landed.length, 2);
});

test("search keeps lazy windowing, sorts only when its inputs change, and uses original identities", async context => {
    const h = await pickerHarness(context, { margin: 38 });
    const w = await languageWindow(context, h);
    w.open();
    await h.settle(w.list.props);
    const initialSorts = w.sorts.length, initialFilters = w.filters.length, choices = w.list.props.options;
    w.settings.currentSelectedTranslationEngines.state = "pending";
    w.render();
    assert.strictEqual(w.list.props.options, choices);
    assert.equal(w.sorts.length, initialSorts);
    assert.equal(w.filters.length, initialFilters);
    w.settings.currentSelectedTranslationEngines.state = "ok";
    w.render();
    const oldKey = w.list.key;
    find(w.tree, node => node.type === "input").props.onChange({ target: { value: "Arabic" } });
    w.render();
    assert.notEqual(w.list.key, oldKey, "new filter resets virtual measurements and focus indices");
    assert.equal(w.sorts.length, initialSorts, "search filters the memoized sort");
    assert.equal(w.list.props.virtualized, true);
    assert.ok(w.list.props.options.length > 0 && w.list.props.options.length < 50);
    assert.ok(w.list.props.options.every(entry => entry.language === "Arabic"));
    // React remounts this keyed list on a filter change.
    h.runtime.unmount();
    const filtered = await pickerHarness(context, { margin: 38 });
    await filtered.settle(w.list.props);
    assert.ok(filtered.virtualProps);
    assert.ok(filtered.nodes.size < w.list.props.options.length);
    assert.equal(w.list.props.initialIndex, -1);
    const first = w.list.props.options[0];
    const input = find(w.tree, node => node.type === "input");
    input.props.onKeyDown({ key: "Enter", nativeEvent: { isComposing: true } });
    assert.equal(w.picked.length, 0);
    input.props.onKeyDown({ key: "Enter", preventDefault() {} });
    assert.strictEqual(w.picked[0], first);
    assert.ok(languages.includes(first));
    w.i18n.language = "ja";
    w.render();
    assert.equal(w.sorts.length, initialSorts + 1);
    w.settings.currentSelectableLanguageList = { state: "ok", data: languages.slice(0, 60) };
    w.render();
    assert.equal(w.sorts.length, initialSorts + 2);
});

test("grid jumps to disabled selections keep focus; Tab skips disabled options and preserves columns", async context => {
    const h = await pickerHarness(context, { margin: 38 });
    const options = fonts.slice(0, 100), isDisabled = option => Number(option.id.slice(5)) % 2 === 0;
    await h.settle({ options, columns: 2, isDisabled,
        children: option => React.createElement("button", { key: option.id, disabled: isDisabled(option) }, option.label) });
    h.nodes.get(1).focus();
    h.navigationRef.current.scrollToIndex(70, { focus: true });
    await h.settle();
    assert.equal(h.calls.at(-1)[0], 35);
    assert.equal(h.document.activeElement, h.nodes.get(1));
    h.tree.props.onKeyDown({ key: "Tab", target: h.nodes.get(1), preventDefault() {} });
    await h.settle();
    assert.equal(h.calls.at(-1)[0], 1, "option 3 is in grid row 1");
    assert.equal(h.document.activeElement, h.nodes.get(3));
});

test("jump focus waits for virtua measurement without an idle retry loop and cancels on close", async context => {
    const { h } = await fontPicker(context);
    h.navigationRef.current.scrollToIndex(700, { focus: true });
    h.render();
    h.nodes.get(700).hidden = true;
    h.frame();
    assert.notEqual(h.document.activeElement, h.nodes.get(700));
    assert.equal(h.frames.size, 0, "hidden rows do not start a polling loop");
    h.nodes.get(700).hidden = false;
    h.virtualProps.onResize();
    h.frame();
    h.render();
    assert.equal(h.document.activeElement, h.nodes.get(700));
    h.virtualProps.onResize();
    assert.equal(h.frames.size, 0, "ordinary measurements do not schedule focus work");
    h.navigationRef.current.scrollToIndex(500, { focus: true });
    h.render();
    assert.equal(h.frames.size, 1);
    h.runtime.unmount();
    assert.equal(h.frames.size, 0);
    assert.equal(h.navigationRef.current, null);
});

test("font selection reaches the existing appearance setter and closes the settings picker", async context => {
    const h = await pickerHarness(context), runtime = hooks(), picked = [];
    const rows = await loadModule(new URL("./VrSettingsRows.jsx", import.meta.url), hooks(), {
        "./VrPickerList": { VrPickerList: h.VrPickerList },
    });
    const { VrSettingsWindow } = await loadModule(new URL("./VrSettingsWindow.jsx", import.meta.url), runtime, {
        "../../logics/common/languageNames.js": languageNames,
        "../../logics/common/featureLabel.js": featureLabel,
        "@useI18n": { useI18n: () => ({ t: key => key, i18n: { language: "en" } }) },
        "@logics_common": { useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: true } }) },
        "@logics_configs": { useAppearance: () => ({ currentUiLanguage: { data: "en" },
            currentSelectedFontFamily: { state: "ok", data: "font-700" }, setSelectedFontFamily: value => picked.push(value) }), useOthers: () => ({}) },
        "@store": { useStore_SelectableFontFamilyList: () => ({ currentSelectableFontFamilyList: {
            state: "ok", data: Object.fromEntries(fonts.map(option => [option.id, option.label])),
        } }) },
        "@ui_configs": { ui_configs: { selectable_ui_languages: [] } },
        "./VrWindow": { VrWindow: () => null }, "./VrSettingsRows": rows,
        "../app/config_page/setting_section/setting_box/_components/compute_device/computeDeviceOptions": {},
        "../../logics/configs/cloudTranscription": {}, "../../logics/configs/ctranslate2License": {},
    });
    h.scroll.querySelector = () => ({ focus() {} });
    const render = () => runtime.render(VrSettingsWindow, {}, root => {
        const picker = find(root, node => node.props["data-vr-settings-list"] === "picker");
        if (picker) picker.ref.current = h.scroll;
    });
    let tree = render();
    find(tree, node => node.type === "button" && find(node, child => child.props?.text === "config_page.side_menu_labels.appearance")).props.onClick();
    tree = render();
    const category = find(tree, node => node.type?.name === "Category");
    const appearance = category.type(category.props);
    const controls = appearance.type(appearance.props);
    find(controls, node => node.type === rows.SelectRow && node.props.label === "config_page.appearance.font_family.label").props.onOpen();
    tree = render();
    const picker = find(tree, node => node.type === rows.Picker);
    await h.settle(find(rows.Picker(picker.props), node => node.type === h.VrPickerList).props);
    h.nodes.get(701).element.props.onClick();
    assert.deepEqual(picked, ["font-701"]);
    assert.equal(find(render(), node => node.type === rows.Picker), null);
    runtime.unmount();
});

test("search with no matches renders no options and cannot select; clearing restores the full list", async context => {
    const h = await pickerHarness(context), w = await languageWindow(context, h);
    w.open();
    find(w.tree, node => node.type === "input").props.onChange({ target: { value: "no-such-language" } });
    w.render();
    await h.settle(w.list.props);
    assert.ok(h.virtualProps);
    assert.equal(h.nodes.size, 0);
    assert.ok(find(w.tree, node => node.props.children === "main_page.language_selector.no_results"));
    const input = find(w.tree, node => node.type === "input");
    input.props.onKeyDown({ key: "Enter" });
    assert.equal(w.picked.length, 0);
    input.props.onChange({ target: { value: "" } });
    w.render();
    assert.equal(w.list.props.options.length, 135);
    assert.equal(w.list.props.initialIndex, -1, "clearing search returns to the top instead of the selected row");
});

test("a selected language far down the list is revealed, disabled and labelled on opening", async context => {
    const h = await pickerHarness(context, { margin: 38 }), w = await languageWindow(context, h, "ja");
    const selected = languages.find(entry => entry.language === "Japanese");
    w.settings.currentSelectedYourLanguages = { state: "ok", data: { 1: { 1: selected } } };
    w.render();
    w.open();
    await h.settle(w.list.props);
    const index = w.list.props.options.indexOf(selected);
    assert.ok(index > 50);
    assert.equal(h.calls.at(-1)[0], Math.floor(index / 2));
    const button = h.nodes.get(index).element;
    assert.equal(button.props.disabled, true);
    assert.equal(button.props["aria-pressed"], true);
    assert.match(button.props["aria-label"], /日本語/);
    button.props.onClick();
    assert.equal(w.picked.length, 0);
    const group = languageJumpGroups(w.list.props.options.map(entry => languageNames.createLanguageNames("ja").name(entry).language), "ja").find(group => group.id === "ハ");
    find(w.tree, node => node.props["data-vr-language-jump"] === "ハ").props.onClick();
    await h.settle();
    assert.equal(h.calls.at(-1)[0], Math.floor(group.index / 2));
});

test("adding a target preserves the existing ordered setter payload", async context => {
    const h = await pickerHarness(context), w = await languageWindow(context, h);
    w.open("add");
    await h.settle(w.list.props);
    const entry = w.list.props.options[0];
    h.nodes.get(0).element.props.onClick();
    assert.equal(w.picked.length, 1);
    assert.equal(w.picked[0].length, 2);
    assert.strictEqual(w.picked[0][0], w.settings.currentSelectedTargetLanguages.data[1][1]);
    assert.strictEqual(w.picked[0][1], entry);
});

test("stationary hover follows virtual rows mounting and unmounting, coalescing scroll and layout", async context => {
    let hover;
    context.after(() => hover?.dispose());
    const { h } = await fontPicker(context), writes = [], mutations = [];
    const root = { ...eventTarget(), contains: node => [...h.nodes.values()].includes(node), querySelectorAll: () => [] };
    stubGlobals(context, { window: eventTarget(), MutationObserver: class {
        constructor(callback) { mutations.push(callback); }
        observe() {}
        disconnect() {}
    } });
    let hit;
    h.document.elementFromPoint = () => hit;
    const asTarget = node => {
        node.closest = selector => selector === "button, [data-vr-hoverable]" ? node : null;
        node.setAttribute = name => writes.push([node, "set", name]);
        node.removeAttribute = name => writes.push([node, "remove", name]);
        return node;
    };
    hover = trackVrPointerHover(root);
    hit = asTarget(h.nodes.get(1));
    const original = hit;
    hover.setPointer({ x: 100, y: 200 });
    h.frame();
    h.scroll.scrollTop = 40000;
    h.render();
    assert.ok(![...h.nodes.values()].includes(original));
    hit = asTarget(h.nodes.get(500));
    root.dispatch("scroll");
    mutations[0]([{ type: "childList" }]);
    assert.equal(h.frames.size, 1);
    h.frame();
    assert.deepEqual(writes, [[original, "set", "data-vr-hover"], [original, "remove", "data-vr-hover"], [hit, "set", "data-vr-hover"]]);
    mutations[0]([{ type: "childList" }]);
    h.frame();
    assert.equal(writes.length, 3);
    assert.equal(h.frames.size, 0);
});
