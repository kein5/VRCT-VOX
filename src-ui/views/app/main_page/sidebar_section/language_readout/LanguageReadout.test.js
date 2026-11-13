import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { hooks, loadModule, find } from "../../../../../logics/test/hookHarness.js";
import * as languageNames from "../../../../../logics/common/languageNames.js";

const entry = (language, country, enable = true) => ({ language, country, enable });
const t = (key, options) => options ? `${options.from} → ${options.to}` : key;

async function setup({ ui = "ja", yours = entry("Japanese", "Japan"), targets = { 1: entry("English", "United States"), 2: entry("Korean", "South Korea", false), 3: entry("French", "France", false) }, preset = "1" } = {}) {
    const runtime = hooks(), toggled = [];
    const { LanguageReadout } = await loadModule(new URL("./LanguageReadout.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t, i18n: { language: ui } }) },
        "../../../../../logics/common/languageNames.js": languageNames,
        "@logics_main": {
            useIsMainPageCompactMode: () => ({ toggleIsMainPageCompactMode: () => toggled.push(true) }),
            useLanguageSettings: () => ({ currentSelectedPresetTabNumber: { data: preset },
                currentSelectedYourLanguages: { data: yours && { 1: { 1: yours }, 2: { 1: entry("English", "United States") } } },
                currentSelectedTargetLanguages: { data: targets && { 1: targets, 2: { 1: entry("Japanese", "Japan") } } } }),
        },
    });
    return { button: runtime.render(LanguageReadout), toggled };
}
const names = button => button.props.children.filter(child => child?.props?.className === "name").map(child => child.props.children);

test("the icon rail shows your language and the other side's, in the UI language", async () => {
    const s = await setup();
    assert.deepEqual(names(s.button), ["日本語", "英語"]);
    assert.equal(s.button.props.title, "日本語 → 英語");
    assert.equal(s.button.props["aria-label"], "main_page.language_settings: 日本語 → 英語");
    assert.equal(find(s.button, node => node.props?.className === "more"), null);
    assert.deepEqual(names((await setup({ ui: "en" })).button), ["Japanese", "English"]);
});

test("more languages on the other side are counted, and disabled ones are not", async () => {
    const s = await setup({ targets: { 1: entry("English", "United States"), 2: entry("Korean", "South Korea"), 3: entry("French", "France", false) } });
    assert.deepEqual(names(s.button), ["日本語", "英語"]);
    assert.equal(find(s.button, node => node.props?.className === "more").props.children.join(""), "+1");
    assert.equal(s.button.props.title, "日本語 → 英語 +1");
});

test("it follows the selected preset and opens the rail when pressed", async () => {
    const s = await setup({ preset: "2" });
    assert.deepEqual(names(s.button), ["英語", "日本語"]);
    s.button.props.onClick();
    assert.deepEqual(s.toggled, [true]);
    assert.equal(s.button.props.type, "button");
});

test("before the languages arrive nothing is drawn", async () => {
    assert.equal((await setup({ yours: null })).button, null);
    assert.equal((await setup({ targets: null })).button, null);
    assert.equal((await setup({ targets: { 1: entry("English", "United States", false) } })).button, null);
});

test("long names end in an ellipsis; on is tinted and named in the rail", () => {
    const css = readFileSync(new URL("./LanguageReadout.module.scss", import.meta.url), "utf8");
    assert.match(css, /\.name \{[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap/);
    const switches = readFileSync(new URL("../main_function_switch/MainFunctionSwitch.module.scss", import.meta.url), "utf8");
    assert.match(switches, /&\.is_active \{\s*background-color: var\(--vox_highlight_tint\);/);
    assert.match(switches, /&\.is_active:not\(\.is_pending\) \{\s*color: var\(--vox_state_active\);/);
    const jsx = readFileSync(new URL("../main_function_switch/MainFunctionSwitch.jsx", import.meta.url), "utf8");
    assert.match(jsx, /title=\{statusText \?\? \(currentIsMainPageCompactMode\.data \? switchLabel : undefined\)\}/);
});
