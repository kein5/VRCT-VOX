import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const variables = Object.fromEntries([...read("../_index_css/variables.css").matchAll(/(--[\w-]+):\s*([^;]+);/g)]
    .map(([, key, value]) => [key, value.trim()]));
const color = token => {
    const value = variables[token] ?? token;
    const alias = /^var\((--[\w-]+)\)$/.exec(value);
    return alias ? color(alias[1]) : value;
};
const luminance = token => {
    const rgb = color(token).slice(1).match(/../g).map(channel => parseInt(channel, 16) / 255)
        .map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
};
const contrast = (foreground, background) => {
    const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
};
const box = "setting_section/setting_box/";

// Baselines are the audited full-opacity sRGB pairs. Each actual new pair is
// resolved through variables.css, including the semantic hover alias.
const pairs = [
    ["save failure", "--error_bc_color", "--dark_900_color", "--vox_state_failed", "--dark_900_color", 4.5],
    ["secondary voice hover", "--dark_200_color", "--dark_600_color", "--dark_200_color", "--vox_secondary_hover", 4.5],
    ["OCR reset/refresh hover", "--dark_200_color", "--dark_600_color", "--dark_200_color", "--vox_secondary_hover", 4.5],
    ["word Add hover", "--dark_200_color", "--primary_500_color", "--dark_200_color", "--primary_650_color", 4.5],
    ["delete resting", "--error_bc_color", "--dark_800_color", "--vox_state_failed", "--dark_800_color", 3],
    ["delete hover", "--error_bc_color", "--dark_750_color", "--vox_state_failed", "--dark_825_color", 3],
    ["delete pressed", "--error_bc_color", "--dark_850_color", "--vox_state_failed", "--dark_850_color", 3],
];
for (const [name, oldFg, oldBg, fg, bg, minimum] of pairs) {
    test(`${name}: changed CSS pair meets ${minimum}:1 and improves the audited ratio`, () => {
        assert.ok(contrast(fg, bg) >= minimum, `${name}: ${contrast(fg, bg)}`);
        assert.ok(contrast(fg, bg) >= contrast(oldFg, oldBg));
    });
}

test("the repaired selectors use the measured tokens; existing shared token values stay unchanged", () => {
    assert.match(read("topbar/Topbar.module.scss"), /\.state\.is_failed\s*{\s*color: var\(--vox_state_failed\)/);
    assert.match(read(box + "advanced_settings/VoiceSettings.module.scss"), /button:hover:enabled\s*{\s*background: var\(--vox_secondary_hover\)/);
    assert.equal((read(box + "ocr/Ocr.module.scss").match(/background: var\(--vox_secondary_hover\)/g) ?? []).length, 2);
    const word = read(box + "_components/word_filter/WordFilter.module.scss");
    assert.match(word, /\.delete_svg\s*{[^}]*color: var\(--vox_state_failed\)/);
    assert.match(word, /&\.delete\s*{[^}]*&:hover\s*{\s*background-color: var\(--dark_825_color\)/);
    assert.match(word, /\.add_button\s*{[^}]*&:hover\s*{\s*background-color: var\(--primary_650_color\)/);
    for (const [token, expected] of Object.entries({
        "--error_bc_color": "#bb4448", "--vox_state_failed": "#f08a85",
        "--dark_200_color": "#edf3ff", "--dark_600_color": "#798ca8", "--dark_800_color": "#344662",
        "--dark_825_color": "#2d3e58", "--primary_500_color": "#3f7bf2", "--primary_650_color": "#235bcc",
    })) assert.equal(color(token), expected, token);
    // Inherited secondary text is also safe on the new hover; white primary
    // actions keep their own hover rule and retain their AA contrast.
    assert.ok(contrast("--vox_secondary_text", "--vox_secondary_hover") >= 4.5);
    assert.ok(contrast("--dark_50_color", "--primary_550_color") >= 4.5);
});

test("NLLB consent restores a native checkbox and visible keyboard focus", () => {
    const css = read(box + "translation/Translation.module.scss").split(".license_check {")[1].split(".license_actions")[0];
    assert.match(css, /appearance: auto/);
    assert.match(css, /-webkit-appearance: checkbox/);
    assert.match(css, /&:focus-visible\s*{\s*outline: \.2rem solid var\(--primary_200_color\)/);
    assert.match(css, /flex-shrink: 0/);
});

test("available-width breakpoints stack rows at 400px/100% and 800px/200%, including fieldset padding", () => {
    const voice = read(box + "advanced_settings/VoiceSettings.module.scss");
    const row = read(box + "_components/form_row/FormRow.module.scss");
    const legacy = read(box + "_templates/Templates.module.scss");
    const breakpoint = css => Number(/@container \(max-width: ([\d.]+)rem\)/.exec(css)[1]);
    assert.equal(breakpoint(voice), 16 + 18 + 1.6);
    assert.equal(breakpoint(row), breakpoint(voice));
    assert.equal(breakpoint(legacy), 16 + 24 + 2 + 2 * 2);
    assert.match(read("setting_section/SettingSection.module.scss"), /container-type: inline-size/);
    assert.match(voice, /form, fieldset\s*{[^}]*container-type: inline-size/);
    for (const css of [voice, row]) {
        assert.match(css, /grid-template-columns: minmax\(0, 1fr\)/);
        assert.match(css, /overflow-wrap: anywhere/);
        assert.ok(css.includes("@media (max-width: 700px)"), "preserve DESIGN.md's narrow-window stacking");
    }
    assert.match(legacy, /\.container\s*{\s*flex-direction: column; align-items: stretch/);
    for (const [width, scale] of [[400, 1], [800, 2]]) {
        const rem = 10 * scale; // root.css: 62.5% of the default 16px, then UI scale.
        const available = width - (5.6 + 2 * 1.6) * rem;
        const fieldset = available - (2 * 1.6 + 2 * .1) * rem;
        const legacyContent = available - 2 * 2 * rem;
        assert.equal(available, 312 * scale);
        assert.equal(fieldset, 278 * scale);
        assert.equal(legacyContent, 272 * scale);
        assert.ok(available < breakpoint(voice) * rem);
        assert.ok(fieldset < breakpoint(row) * rem);
        assert.ok(available < breakpoint(legacy) * rem);
        assert.ok(24 * rem <= legacyContent, "24rem URL/key fits after stacking");
        assert.ok(legacyContent - (3.6 + 1) * rem > 0, "color swatch leaves room for a shrinking input");
    }
});

test("legacy fixed-width inputs are capped by their row and can shrink beside the color swatch", () => {
    const entry = read(box + "_components/_atoms/_entry/_Entry.module.scss");
    assert.match(entry, /\.entry_container\s*{[^}]*min-width: 0;[^}]*max-width: 100%/);
    assert.match(entry, /\.entry_input_area\s*{[^}]*min-width: 0/);
    for (const path of ["entry_with_save_button/EntryWithSaveButton", "auth_key/AuthKey", "color_entry_with_save_button/ColorEntryWithSaveButton"]) {
        assert.match(read(box + "_components/" + path + ".module.scss"), /\.container\s*{[^}]*min-width: 0;[^}]*max-width: 100%;[^}]*flex-shrink: 1/);
    }
    assert.match(read(box + "_components/auth_key/AuthKey.module.scss"), /\.entry_section_wrapper\s*{[^}]*max-width: 100%/);
    assert.match(read(box + "_components/label_component/LabelComponent.module.scss"), /overflow-wrap: anywhere/);
});

test("legacy model information wraps above its action inside the padded row, including Japanese button text", () => {
    const radio = read(box + "_components/radio_button/RadioButton.module.scss");
    const column = radio.slice(radio.indexOf("&.column {"), radio.indexOf("&.has_desc:not(.column)"));
    const download = read(box + "_components/_atoms/_download_button/_DownloadButton.module.scss");
    assert.match(column, /width: 100%;\s*min-width: 0/);
    assert.match(column, /\.radio_button_container\s*{[^}]*flex-wrap: wrap/);
    assert.match(column, /\.radio_button_wrapper\s*{[^}]*flex: 1 1 24rem;[^}]*min-width: 0;[^}]*max-width: 100%/);
    assert.match(column, /\.label_heading_wrapper\s*{\s*flex-wrap: wrap/);
    assert.match(column, /\.radio_button_label\s*{[^}]*flex-shrink: 1;[^}]*overflow-wrap: anywhere/);
    assert.match(column, /\.radio_button_desc\s*{[^}]*overflow-wrap: anywhere/);
    assert.match(download, /\.download_container\s*{[^}]*width: 9rem;[^}]*min-width: 0;[^}]*max-width: 100%/);
    assert.match(download, /\.download_button_label\s*{[^}]*white-space: normal;[^}]*overflow-wrap: anywhere/);
    const labelBasis = Number(/flex: 1 1 ([\d.]+)rem/.exec(column)[1]);
    const actionWidth = Number(/width: ([\d.]+)rem/.exec(download.split(".download_container {")[1])[1]);
    const gap = Number(/gap: ([\d.]+)rem/.exec(radio.split("\n.radio_button_container {")[1])[1]);
    assert.equal(labelBasis + actionWidth + gap, 34.2);
    assert.ok(actionWidth >= 6 * 1.2 + 2 * .8, "ダウンロード and its padding fit the action");
    // The reviewer measured a 672px scroller at 800px / 200%. The other
    // case uses the existing 5.6rem compact rail at 400px / 100%.
    for (const [scroller, rem] of [[672, 20], [344, 10]]) {
        const section = scroller - 2 * 1.6 * rem;
        const row = section - 2 * 2 * rem;
        assert.ok(section < (labelBasis + actionWidth + gap) * rem);
        assert.ok(row < (labelBasis + actionWidth + gap) * rem);
        assert.ok(actionWidth * rem <= row);
        assert.ok(row - (2 * .8 + 2 + 1) * rem > 0, "model text retains space after label padding, radio and gap");
    }
});

test("word-filter input/Add and export controls wrap within the actual available width", () => {
    const word = read(box + "_components/word_filter/WordFilter.module.scss");
    const entry = word.split(".entry_section_wrapper {")[1].split(".add_button")[0];
    assert.match(entry, /flex-wrap: wrap/);
    assert.match(entry, /width: 100%;\s*min-width: 0/);
    assert.match(entry, /> :first-child\s*{\s*flex: 1 1 18rem; min-width: 0; max-width: 30rem/);
    assert.match(word, /\.add_button\s*{[^}]*max-width: 100%;[^}]*overflow-wrap: anywhere/);
    const shared = read(box + "shared_items/SharedItems.module.scss");
    for (const selector of ["auto_export_message_logs_container", "auto_export_message_logs_switch_section_container"]) {
        const rules = shared.split("." + selector + " {")[1].split("}")[0];
        assert.match(rules, /flex-wrap: wrap/);
        assert.match(rules, /min-width: 0/);
        assert.match(rules, /max-width: 100%/);
    }
    for (const [scroller, rem] of [[672, 20], [344, 10]]) {
        const row = scroller - (3.2 + 4) * rem;
        const add = (2 * 1.4 + 2 * 1.2) * rem; // 追加 + button padding.
        assert.ok(18 * rem + 2 * rem + add <= row, "input yields space to Add");
        assert.ok(30 * rem + 2 * rem + add > row, "old fixed preference would overflow");
        const exportActions = (2.4 + 4 + 2.8 + 4 + 1.2) * rem;
        assert.ok(exportActions <= row);
        assert.ok(16 * rem + 2 * rem + exportActions > row, "export actions must wrap below their label");
    }
});

test("search and every top-bar action occupy disjoint shared-grid areas with automatically reserved height", () => {
    const page = read("ConfigPage.module.scss"), top = read("topbar/Topbar.module.scss");
    const search = read("search_bar/SearchBar.module.scss"), sidebar = read("sidebar_section/SidebarSection.module.scss");
    assert.match(page, /\.content_wrapper\s*{\s*display: contents/);
    assert.match(top, /\.container\s*{\s*display: contents/);
    assert.match(search, /\.search_wrapper\s*{\s*grid-area: search;\s*position: relative/);
    assert.match(search, /&\.is_small\s*{/, "retain the class used by the unchanged SearchBar JSX");
    assert.match(sidebar, /grid-area: sidebar/);
    assert.match(page, /\.main_container\s*{\s*grid-area: main;\s*min-width: 0;\s*min-height: 0/);
    assert.ok(!page.includes("padding-top:"), "content starts below intrinsic header rows, not a fixed estimate");
    assert.match(sidebar, /padding-top: 0/);
    assert.match(page, /grid-template-rows: auto minmax\(0, 1fr\)/);
    assert.equal((page.match(/grid-template-rows: auto auto minmax\(0, 1fr\)/g) ?? []).length, 2);
    assert.match(page, /@media \(max-width: 800px\)/);
    assert.match(page, /html\[data-narrow\]/);
    const areas = [...page.matchAll(/grid-template-areas:\s*((?:"[^"]+"\s*)+);/g)]
        .map(([, value]) => [...value.matchAll(/"([^"]+)"/g)].map(([, row]) => row.split(" ")));
    assert.deepEqual(areas, [
        [["search", "stop", "save", "back"], ["sidebar", "main", "main", "main"]],
        [["search", "search", "stop", "stop"], [".", "save", "save", "back"], ["sidebar", "main", "main", "main"]],
        [["search", "search", "stop", "stop"], [".", "save", "save", "back"], ["sidebar", "main", "main", "main"]],
    ]);
    for (const grid of areas) {
        for (const area of ["search", "stop", "save", "back", "sidebar", "main"]) {
            const cells = grid.flatMap((row, y) => row.flatMap((name, x) => name === area ? [[x, y]] : []));
            const xs = cells.map(([x]) => x), ys = cells.map(([, y]) => y);
            for (let y = Math.min(...ys); y <= Math.max(...ys); y++) {
                for (let x = Math.min(...xs); x <= Math.max(...xs); x++) {
                    assert.equal(grid[y][x], area, "every area is rectangular and shares no cells");
                }
            }
        }
    }
    for (const [selector, area] of [["stop_actions", "stop"], ["save_slot", "save"], ["back", "back"]]) {
        assert.match(top, new RegExp("\\." + selector + "\\s*\\{\\s*grid-area: " + area));
    }
    assert.match(top, /\.save_bar\s*{[^}]*min-width: 0;[^}]*flex-wrap: wrap/);
    assert.match(top, /\.summary\s*{[^}]*min-width: 0;[^}]*flex-wrap: wrap/);
    assert.match(top, /\.stop\s*{[^}]*flex-wrap: wrap;[^}]*max-width: 100%;[^}]*white-space: normal/);
    assert.match(top, /\.stop_actions\s*{[^}]*flex-wrap: wrap/);
    assert.match(top.split("@mixin narrow_header")[1], /\.stop_actions\s*{[^}]*max-width: 24rem/);
    assert.match(top, /@media \(max-width: 800px\)\s*{\s*@include narrow_header/);
    assert.match(top, /html\[data-narrow\][^}]*@include narrow_header/);
});

test("header width budgets leave search usable even with queued/muted actions at both requested scales", () => {
    // Budgets use Japanese full-width glyphs as 1em. CSS still wraps for fonts,
    // counts or translations wider than these estimates; these are not screenshots.
    const stop = 6 * 1.4 + 2 * 1.2 + 2 * .1;
    const mute = 4 * 1.4 + 2 * 1.2 + 2 * .1;
    const searchChrome = 2 * .8 + 2 * .1 + 1.5 + 2 * .7 + 1.2 + 2 * .2;
    for (const [pageWidth, rem] of [[800, 20], [784, 20], [400, 10], [392, 10]]) {
        for (const stopWidth of [stop + mute + .8, 24]) {
            const stopArea = (stopWidth + 1.6) * rem; // Includes its right margin.
            const searchArea = pageWidth - stopArea;
            const searchWidth = searchArea - 2 * 1.6 * rem;
            assert.ok(searchWidth > searchChrome * rem, "input remains wider than its icon/clear/padding");
            const searchRight = searchArea - 1.6 * rem;
            const stopLeft = searchArea;
            const stopRight = stopLeft + stopWidth * rem;
            assert.ok(searchRight + .8 * rem <= stopLeft, "focus outlines fit the gap");
            assert.ok(stopRight <= pageWidth - 1.6 * rem);
        }
        const saveWidth = pageWidth - (5.6 + 5 + 1.6 + 1.6 + .8) * rem;
        assert.ok(saveWidth > (2 * (2 * 1.4 + 2 * 1.4) + .8 + 2) * rem,
            "save/discard fit; state/count can wrap into their own line");
    }
    // At 1200px/100%, search is back in the 20.8rem rail; all controls use
    // the single header row, including the longer Japanese stop/mute labels.
    const wideStop = (7 * 1.4 + 2.6) + (9 * 1.4 + 2.6) + .8;
    const wideBack = 2 * 1.4 + .8 + 1.8 + 2 * 1.6;
    const wideSave = 120 - 20.8 - (wideStop + .8) - (wideBack + 1.6) - .8;
    assert.ok(20.8 - 3.2 > searchChrome);
    assert.ok(wideSave > 10 + 2 * (5 * 1.4 + 2 * 1.4) + 1.6 + 2);
});
