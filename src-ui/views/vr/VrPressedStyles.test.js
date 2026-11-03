import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { compileString } from "sass";

for (const [file, targets] of [
    ["VrSettingsWindow.module.scss", [".button", ".clickable"]],
    ["VrWindow.module.scss", [".close_button"]],
    ["VrLanguageWindow.module.scss", [".language_window button", ".language_window summary"]],
]) {
    test(`${file} gives enabled VR controls immediate, layout-preserving pressed colour`, async () => {
        const source = await readFile(new URL(file, import.meta.url), "utf8");
        const css = compileString(source).css;
        for (const target of targets) {
            const rules = [...css.matchAll(/([^{}]+)\{([^{}]+)\}/g)].filter(([, selectors]) =>
                selectors.split(",").some(selector => selector.trim().startsWith(`${target}:active`)));
            assert.ok(rules.length, `Missing pressed rule for ${target}`);
            for (const [, selectors, body] of rules) {
                for (const selector of selectors.split(",")) {
                    assert.match(selector, /:not\(:disabled\)/);
                    assert.match(selector, /:not\(\[aria-disabled=["']?true["']?\]\)/);
                }
                assert.match(body, /background-color:\s*var\(--primary_600_color\)/);
                assert.match(body, /transition:\s*none/);
                const properties = [...body.matchAll(/([\w-]+):/g)].map(([, property]) => property);
                assert.deepEqual(properties.sort(), ["background-color", "transition"]);
            }
        }
    });
}

test("launcher and toolbar buttons use the shared pressed style", async () => {
    for (const file of ["VrLauncher.jsx", "VrToolbar.jsx"]) {
        const source = await readFile(new URL(file, import.meta.url), "utf8");
        assert.match(source, /import shared from "\.\/VrSettingsWindow\.module\.scss"/);
        assert.match(source, /shared\.button/);
    }
});
