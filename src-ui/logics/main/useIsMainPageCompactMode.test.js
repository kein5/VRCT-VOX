import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../test/hookHarness.js";

async function fixture(saved) {
    const runtime = hooks(), requests = [];
    let narrow = true;
    const store = {
        useStore_IsBreakPoint: () => ({ currentIsBreakPoint: { data: narrow } }),
        useStore_IsMainPageCompactMode: () => ({ currentIsMainPageCompactMode: { data: saved, state: "ok" },
            updateIsMainPageCompactMode: value => { saved = value; } }),
        useStore_IsOpenedLanguageSelector: () => ({ currentIsOpenedLanguageSelector: { data: {} } }),
    };
    const logic = await loadModule(new URL("./useIsMainPageCompactMode.js", import.meta.url), runtime, {
        "@store": store, "@useStdoutToPython": { useStdoutToPython: () => ({
            asyncStdoutToPython: endpoint => requests.push(endpoint) }) },
    });
    const { SidebarSection } = await loadModule(new URL("../../views/app/main_page/sidebar_section/SidebarSection.jsx", import.meta.url), runtime, {
        "@store": store, "@logics_main": logic, "./logo/Logo": { Logo: "logo" },
        "./main_function_switch/MainFunctionSwitch": { MainFunctionSwitch: "switches" },
        "./language_settings/LanguageSettings": { LanguageSettings: "languages" },
        "./language_readout/LanguageReadout": { LanguageReadout: "readout" },
        "./open_settings/OpenSettings": { OpenSettings: "settings" },
    });
    const { SidebarCompactModeButton } = await loadModule(new URL("../../views/app/main_page/main_section/top_bar/sidebar_compact_mode_button/SidebarCompactModeButton.jsx", import.meta.url), runtime, {
        "@logics_main": logic,
    });
    const render = () => runtime.render(() => ({ sidebar: SidebarSection(), button: SidebarCompactModeButton() }));
    return { render, requests, setNarrow: value => { narrow = value; }, saved: () => saved };
}

for (const saved of [false, true]) {
    test(`automatic narrow sidebar expands and collapses without saving (saved compact=${saved})`, async () => {
        const s = await fixture(saved);
        let tree = s.render();
        assert.equal(find(tree.sidebar, node => node.type === "languages"), null);
        assert.ok(find(tree.sidebar, node => node.type === "readout"), "the icon rail keeps the language pair in sight");
        assert.ok(!tree.button.props.disabled, "keyboard and pointer activation must remain available");
        assert.equal(tree.button.props.type, "button");
        assert.equal(tree.button.props["aria-expanded"], false);
        tree.button.props.onClick();
        tree = s.render();
        assert.ok(find(tree.sidebar, node => node.type === "languages"));
        assert.equal(find(tree.sidebar, node => node.type === "readout"), null);
        assert.equal(tree.button.props["aria-expanded"], true);
        tree.button.props.onClick();
        tree = s.render();
        assert.equal(find(tree.sidebar, node => node.type === "languages"), null);
        assert.deepEqual(s.requests, []);
        assert.equal(s.saved(), saved);
    });

    test(`leaving narrow mode restores the saved preference and clears temporary expansion (${saved})`, async () => {
        const s = await fixture(saved);
        s.render().button.props.onClick();
        assert.equal(s.render().button.props["aria-expanded"], true);
        s.setNarrow(false);
        assert.equal(s.render().button.props["aria-expanded"], !saved);
        s.setNarrow(true);
        assert.equal(s.render().button.props["aria-expanded"], false);
        assert.deepEqual(s.requests, []);
        s.setNarrow(false);
        s.render().button.props.onClick();
        assert.deepEqual(s.requests, [`/set/${saved ? "disable" : "enable"}/main_window_sidebar_compact_mode`]);
        assert.equal(s.saved(), saved, "wide changes still wait for the backend acknowledgement");
    });
}
