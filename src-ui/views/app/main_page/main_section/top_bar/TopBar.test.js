import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { hooks, loadModule, find, eventTarget, stubGlobals } from "../../../../../logics/test/hookHarness.js";

const all = (tree, predicate, found = []) => { find(tree, node => { if (predicate(node)) found.push(node); return false; }); return found; };
const t = (key, options) => options ? `${key}:${JSON.stringify(options)}` : key;

async function menu(context, values = {}) {
    const runtime = hooks(), calls = [], document = eventTarget();
    // Unmount first: the menu's cleanup still needs the document this test provides.
    context.after(() => runtime.unmount());
    stubGlobals(context, { document });
    const state = { foreground: false, sync: false, small: false, large: false, osc: true, pending: false, ...values };
    const button = await loadModule(new URL("./right_side_components/_buttons/OpenQuickSettingButton.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t }) },
    });
    const { RightSideComponents } = await loadModule(new URL("./right_side_components/RightSideComponents.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t }) },
        "@store": { useStore_OpenedQuickSetting: () => ({ updateOpenedQuickSetting: value => calls.push(["open", value]) }) },
        "@logics_common": {
            useSoftwareVersion: () => ({ currentLatestSoftwareVersionInfo: { data: { is_update_available: false } } }),
            useIsOscAvailable: () => ({ currentIsOscAvailable: { data: state.osc }, oscUnavailableLabelKey: "why_unavailable" }),
        },
        "@logics_configs": {
            useAppearance: () => ({ currentUiLanguage: { data: "ja" } }),
            useVr: () => ({ currentIsEnabledOverlaySmallLog: { data: state.small }, currentIsEnabledOverlayLargeLog: { data: state.large } }),
            useOthers: () => ({ currentEnableVrcMicMuteSync: { data: state.sync, state: "ok" }, toggleEnableVrcMicMuteSync: () => calls.push(["sync"]) }),
        },
        "@logics_main": { useMainFunction: () => ({ currentForegroundStatus: { data: state.foreground, state: state.pending ? "pending" : "ok" },
            toggleForeground: () => calls.push(["foreground"]) }) },
        "./_buttons/OpenQuickSettingButton": button,
        "@ui_configs": { generateLocalizedDocumentUrl: () => ({ vrct_document_ui_guide_url: "https://example.invalid/guide" }) },
    });
    const Menu = find(runtime.render(RightSideComponents), node => node.type?.name === "QuickSettingsMenu").type;
    const focused = [];
    const draw = () => {
        const tree = runtime.render(Menu, {}, node => {
            node.ref.current = { contains: target => target === "inside" };
            find(node, child => child.type === "button").ref.current = { focus: () => focused.push("opener") };
        });
        const rows = all(tree, node => node.type === button.OpenQuickSettingButton).map(node => {
            const drawn = node.type(node.props);
            return { props: node.props, button: find(drawn, child => child.type === "button"), note: find(drawn, child => child.type === "p" && child.props.className === "note") };
        });
        return { tree, opener: find(tree, node => node.type === "button"), panel: find(tree, node => node.props?.role === "group"), rows,
            state: find(tree, node => node.props?.className === "menu_state")?.props.children };
    };
    return { draw, calls, document, focused, state };
}

test("the quick settings button says how many of its toggles are on, and opens them in place", async context => {
    const s = await menu(context, { foreground: true, large: true });
    let view = s.draw();
    assert.equal(view.opener.props["aria-expanded"], false);
    assert.equal(view.panel, null);
    assert.equal(view.state, 'main_page.quick_settings_on:{"count":2}');
    assert.match(view.opener.props.className, /has_on/);
    view.opener.props.onClick();
    view = s.draw();
    assert.equal(view.opener.props["aria-expanded"], true);
    assert.equal(view.opener.props["aria-controls"], view.panel.props.id);
    assert.deepEqual(view.rows.map(row => [row.props.label, row.props.variable]), [
        ["main_page.foreground", true], ["config_page.others.vrc_mic_mute_sync.label", false], ["config_page.vr.section_label_overlay", true]]);
    assert.deepEqual(view.rows.map(row => row.button.props["aria-pressed"]), [true, false, undefined]);
    assert.equal(view.rows[2].button.props["aria-haspopup"], "dialog");
});

test("nothing on reads as all off", async context => {
    const s = await menu(context);
    const view = s.draw();
    assert.equal(view.state, "main_page.quick_settings_all_off");
    assert.doesNotMatch(view.opener.props.className, /has_on/);
});

test("a toggle is pressed in the open menu; the overlay row closes it and opens its dialog", async context => {
    const s = await menu(context);
    s.draw().opener.props.onClick();
    let view = s.draw();
    view.rows[0].button.props.onClick();
    view.rows[1].button.props.onClick();
    assert.deepEqual(s.calls, [["foreground"], ["sync"]]);
    assert.ok(s.draw().panel, "toggling keeps the menu open");
    s.draw().rows[2].button.props.onClick();
    assert.deepEqual(s.calls.at(-1), ["open", "overlay"]);
    assert.equal(s.draw().panel, null);
});

test("mute sync that cannot be used is disabled and says why", async context => {
    const s = await menu(context, { osc: false });
    s.draw().opener.props.onClick();
    const row = s.draw().rows[1];
    assert.equal(row.button.props.disabled, true);
    assert.equal(row.note.props.children, "why_unavailable");
    row.props.onClickFunction();
    assert.deepEqual(s.calls, []);
    assert.equal(s.draw().rows[0].note, null);
});

test("a pending toggle keeps the keyboard's place: not disabled, and a second press does nothing", async context => {
    const s = await menu(context, { pending: true });
    s.draw().opener.props.onClick();
    const row = s.draw().rows[0];
    assert.equal(row.button.props.disabled, false);
    assert.equal(row.button.props["aria-disabled"], true);
    assert.equal(row.button.props.onClick, undefined);
});

test("Escape closes the menu and returns focus; a press or focus outside closes it; inside does not", async context => {
    const s = await menu(context);
    s.draw().opener.props.onClick();
    assert.ok(s.draw().panel);
    s.document.dispatch("keydown", { key: "a" });
    s.document.dispatch("pointerdown", { target: "inside" });
    s.document.dispatch("focusin", { target: "inside" });
    assert.ok(s.draw().panel);
    s.document.dispatch("keydown", { key: "Escape" });
    assert.equal(s.draw().panel, null);
    assert.deepEqual(s.focused, ["opener"]);
    for (const type of ["pointerdown", "focusin"]) {
        s.draw().opener.props.onClick();
        assert.ok(s.draw().panel);
        s.document.dispatch(type, { target: "outside" });
        assert.equal(s.draw().panel, null);
    }
    assert.deepEqual(s.focused, ["opener"], "leaving does not pull focus back");
    assert.equal(s.document.added.length, s.document.removed.length, "listeners are removed with the menu");
});

test("the main bar leads with stop and mute, drawn with its own short and shortest words", async () => {
    const runtime = hooks(), sent = [];
    const voice = { status: { queued: 2, active: true }, route: { requested_muted: true, ready: true, pending: false, managed: true }, send: path => sent.push(path) };
    const actions = await loadModule(new URL("../../../others/stop_actions/StopActions.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t }) }, "../../../../logics/voice/useVoice": { useVoice: () => voice },
    });
    const { TopBar } = await loadModule(new URL("./TopBar.jsx", import.meta.url), runtime, {
        "./sidebar_compact_mode_button/SidebarCompactModeButton": { SidebarCompactModeButton: "compact" },
        "./right_side_components/RightSideComponents": { RightSideComponents: "right" },
        "../../../others/stop_actions/StopActions": actions,
    });
    const bar = runtime.render(TopBar);
    const leading = find(bar, node => node.props?.className === "leading");
    const [first, second] = leading.props.children;
    assert.equal(first.type, "compact");
    assert.equal(second.type, actions.StopActions);
    const group = runtime.render(second.type, second.props);
    const [stop, mute] = all(group, node => node.type === "button");
    const words = button => Object.fromEntries(all(button, node => node.type === "span").map(node => [node.props.className, node.props.children]));
    assert.deepEqual(words(stop), { long: 'voice_ui.topbar_stop_count:{"count":2}', short: 'voice_ui.topbar_stop_short_count:{"count":2}',
        tiny: 'voice_ui.topbar_stop_tiny_count:{"count":2}' });
    assert.equal(stop.props["aria-label"], 'voice_ui.topbar_stop_count:{"count":2}', "the name stays the full words");
    assert.match(stop.props.className, /is_attention/);
    assert.deepEqual(words(mute), { long: "voice_ui.topbar_mute_mic", short: "voice_ui.topbar_mute_short", tiny: "voice_ui.topbar_muted",
        muted_badge: "voice_ui.topbar_muted" });
    assert.equal(mute.props["aria-pressed"], true);
    stop.props.onClick(); mute.props.onClick();
    assert.deepEqual(sent.slice(-2), ["/run/stop_voice", "/run/resume_voice"]);
});

test("the settings bar draws the same actions without the shortest words", async () => {
    const runtime = hooks();
    const voice = { status: {}, route: {}, send() {} };
    const { StopActions } = await loadModule(new URL("../../../others/stop_actions/StopActions.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t }) }, "../../../../logics/voice/useVoice": { useVoice: () => voice },
    });
    const classes = { stop_actions: "stop_actions", stop: "stop", long: "long", short: "short", is_attention: "is_attention",
        is_pressed: "is_pressed", muted_badge: "muted_badge" };
    const group = runtime.render(StopActions, { classes });
    assert.deepEqual(all(group, node => node.type === "span").map(node => node.props.className), ["long", "short", "long", "short"]);
    const [, mute] = all(group, node => node.type === "button");
    assert.equal(mute.props["aria-pressed"], undefined, "no reported state, no toggle");
});

test("the main bar's stylesheet hides the long words and swaps to the shortest when narrow; strings exist in en and ja", () => {
    const css = readFileSync(new URL("./TopBar.module.scss", import.meta.url), "utf8");
    assert.match(css, /\.long, \.tiny \{ display: none; \}/);
    const narrow = css.split("@mixin narrow_bar")[1].split("@media")[0];
    assert.match(narrow, /\.short \{ display: none; \}/);
    assert.match(narrow, /\.tiny \{ display: inline; \}/);
    assert.match(css, /@media \(max-width: 800px\) \{ @include narrow_bar; \}/);
    assert.match(css, /:global\(html\[data-narrow\]\) \{ @include narrow_bar; \}/);
    for (const language of ["en", "ja"]) {
        const strings = yaml.load(readFileSync(new URL(`../../../../../../locales/${language}.yml`, import.meta.url), "utf8"));
        for (const key of ["quick_settings", "quick_settings_on", "quick_settings_all_off"]) assert.equal(typeof strings.main_page[key], "string");
        for (const key of ["topbar_stop_tiny", "topbar_stop_tiny_count"]) assert.equal(typeof strings.voice_ui[key], "string");
    }
});
