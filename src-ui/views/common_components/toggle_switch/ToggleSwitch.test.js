import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const block = (source, selector) => {
    const start = source.indexOf(`${selector} {`);
    assert.ok(start >= 0, `${selector} is defined`);
    return source.slice(start, source.indexOf("}", start));
};

test("status text cannot narrow a toggle: the switch and its track keep their width", () => {
    assert.match(block(read("./ToggleSwitch.module.scss"), ".toggle_switch_container"), /flex-shrink:\s*0;/);
    assert.match(block(read("../../common_css/mixins.scss"), ".control"), /flex-shrink:\s*0;/);
});

test("main function switches keep a gap between their label and the toggle", () => {
    const main = read("../../app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch.module.scss");
    assert.match(block(main, ".switch_container"), /gap:\s*\.8rem;/);
});
