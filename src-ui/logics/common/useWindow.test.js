import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, stubGlobals } from "../test/hookHarness.js";

// innerSize reports physical pixels; the 800px breakpoint is in CSS pixels
// (scaled by the UI size), like the stylesheet's (max-width: 800px) queries.
for (const [physical, ratio, scaling, narrow] of [
    [1200, 1.5, 100, true], [1202, 1.5, 100, false],
    [1600, 2, 100, true], [1700, 2, 100, false],
    [800, 1, 100, true], [801, 1, 100, false],
    [1800, 1.5, 150, true], [1801, 1.5, 150, false],
]) test(`a ${physical}px window at devicePixelRatio ${ratio} and UI ${scaling}% is ${narrow ? "narrow" : "wide"}`, async context => {
    const attributes = new Set(), updates = [];
    stubGlobals(context, { devicePixelRatio: ratio, document: { documentElement: {
        hasAttribute: name => attributes.has(name),
        toggleAttribute: (name, on) => { if (on) attributes.add(name); else attributes.delete(name); },
    } } });
    const { useWindow } = await loadModule(new URL("./useWindow.js", import.meta.url), hooks(), {
        "@tauri-apps/api/window": {},
        "@store": { store: { appWindow: { innerSize: async () => ({ width: physical }) } },
            useStore_IsBreakPoint: () => ({ updateIsBreakPoint: value => updates.push(value) }) },
        "@logics_configs": { useAppearance: () => ({ currentUiScaling: { data: scaling } }) },
    });
    await useWindow().asyncUpdateBreakPoint();
    assert.equal(attributes.has("data-narrow"), narrow);
    assert.deepEqual(updates, narrow ? [true] : []);
});
