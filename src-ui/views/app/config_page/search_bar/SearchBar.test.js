import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals, eventTarget } from "../../../../logics/test/hookHarness.js";

const key = name => ({ key: name, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });

async function setup(t, { reducedMotion = false, control = true, delayed = false, guarded = false } = {}) {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const document = { ...eventTarget(), body: {} }, window = { matchMedia: query => {
        assert.equal(query, "(prefers-reduced-motion: reduce)"); return { matches: reducedMotion };
    } };
    let cleanup;
    t.after(() => cleanup?.());
    stubGlobals(t, { document, window, CSS: { escape: value => value.replaceAll('"', '\\"') } });
    const ancestors = { tagName: "DETAILS", open: false, parentElement: { tagName: "DETAILS", open: false } };
    const destination = { matches: selector => selector.startsWith("input,"), closest: () => null, getClientRects: () => [1],
        focus: () => { assert.equal(ancestors.open, true); document.activeElement = destination; } };
    const help = { ...destination, matches: () => false, focus: () => { document.activeElement = help; } };
    const scrolls = [], classes = new Set(), attributes = new Map();
    const row = { ...eventTarget(), parentElement: ancestors, querySelectorAll: () => control ? [help, destination] : [],
        scrollIntoView: options => scrolls.push(options),
        classList: { add: value => classes.add(value), remove: value => classes.delete(value) },
        getAttribute: name => attributes.get(name) ?? null, setAttribute: (name, value) => attributes.set(name, value),
        removeAttribute: name => attributes.delete(name), focus: () => { document.activeElement = row; } };
    let available = !delayed;
    document.querySelector = selector => available && selector.includes('data-setting-id="osc"') ? row : null;
    const hookRuntime = hooks(), tabs = [];
    let proceed;
    const { useConfigSearch } = await loadModule(new URL("../../../../logics/configs/config_page_setter/_aux/useConfigSearch.js", import.meta.url), hookRuntime, {
        "@useI18n": { useI18n: () => ({ t: name => name, i18n: { language: "ja" } }) },
        "@store": { useStore_SelectedConfigTabId: () => ({ currentSelectedConfigTabId: { data: "appearance" }, updateSelectedConfigTabId: tab => tabs.push(tab) }) },
        "@logics_configs": { useOcr: () => ({ currentSelectableOcrSourceLanguageList: { data: {} }, currentOcrSourceLanguage: { data: "ja" } }) },
        "../../../transcription/useRealtimeASR": { useRealtimeASR: () => ({ models: {}, settings: {} }) },
        "../../../common/languageNames.js": { createLanguageNames: () => ({ fromCode: name => name }) },
        "../../../voice/settingsNavigation": { requestSettingsNavigation: fn => { if (guarded) proceed = fn; else fn(); } },
        "@ui_configs": { ui_configs: {} },
        "@root/locales/config.js": { getResource: () => ({ config_page: { advanced_settings: { osc: { label: "OSC", desc: "OSC port" } } } }) },
    });
    const runtime = hooks();
    let hook = hookRuntime.render(useConfigSearch);
    hook.setQuery("OSC"); hook = hookRuntime.render(useConfigSearch);
    const { SearchBar } = await loadModule(new URL("./SearchBar.jsx", import.meta.url), runtime, {
        "@store": { useStore_IsBreakPoint: () => ({ currentIsBreakPoint: { data: false } }) },
        "@logics_configs": { useConfigSearch: () => hook },
        "../sidebar_section/SidebarSection.jsx": { TabIcon: () => null },
    });
    const search = { focus: () => { document.activeElement = search; }, blur: () => { document.activeElement = document.body; } };
    const render = () => find(runtime.render(SearchBar, {}, tree => {
        find(tree, node => node.type === "input").ref.current = search;
    }), node => node.type === "input");
    search.focus(); render().props.onFocus();
    cleanup = () => { runtime.unmount(); hookRuntime.unmount(); };
    return { render, search, document, ancestors, destination, row, scrolls, classes, attributes, tabs,
        setAvailable: () => { available = true; }, accept: () => proceed(), navigate: hook.navigateToSetting };
}

for (const reducedMotion of [false, true]) test(`search Enter opens ancestors and focuses destination (reduced motion: ${reducedMotion})`, async t => {
    const s = await setup(t, { reducedMotion, delayed: true });
    s.render().props.onKeyDown(key("ArrowDown"));
    s.render().props.onKeyDown(key("Enter"));
    assert.equal(s.document.activeElement, s.search); // Keep focus until the destination is mounted.
    t.mock.timers.tick(60);
    s.setAvailable(); t.mock.timers.tick(40);
    assert.deepEqual(s.tabs, ["advanced_settings"]);
    assert.equal(s.ancestors.open, true); assert.equal(s.ancestors.parentElement.open, true);
    assert.equal(s.document.activeElement, s.destination);
    assert.deepEqual(s.scrolls, [{ behavior: reducedMotion ? "instant" : "smooth", block: "center" }]);
    assert.ok(s.classes.has("search_target_highlight"));
});

test("search Escape keeps input focus, closes results and allows typing again", async t => {
    const s = await setup(t);
    const event = key("Escape"); s.render().props.onKeyDown(event);
    assert.equal(event.defaultPrevented, true);
    assert.equal(s.document.activeElement, s.search);
    assert.equal(s.render().props["aria-expanded"], false);
    assert.deepEqual(s.tabs, []);
    s.render().props.onChange({ target: { value: "OSC" } });
    assert.equal(s.render().props["aria-expanded"], true);
});

test("search focuses an empty row temporarily and does not navigate on IME Enter", async t => {
    const s = await setup(t, { control: false });
    s.render().props.onKeyDown({ ...key("Enter"), nativeEvent: { isComposing: true } });
    assert.deepEqual(s.tabs, []);
    s.render().props.onKeyDown(key("Enter")); t.mock.timers.tick(60);
    assert.equal(s.document.activeElement, s.row);
    assert.equal(s.attributes.get("tabindex"), "-1");
    s.row.dispatch("blur", {});
    assert.equal(s.attributes.has("tabindex"), false);
});


test("search waits for the existing unsaved-changes guard before navigating or moving focus", async t => {
    const s = await setup(t, { guarded: true });
    s.render().props.onKeyDown(key("Enter"));
    t.mock.timers.tick(2000);
    assert.deepEqual(s.tabs, []);
    assert.equal(s.document.activeElement, s.search);
    assert.equal(s.ancestors.open, false);
    s.accept(); t.mock.timers.tick(60);
    assert.deepEqual(s.tabs, ["advanced_settings"]);
    assert.equal(s.document.activeElement, s.destination);
});
