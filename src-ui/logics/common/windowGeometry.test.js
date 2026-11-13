import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BUILT_IN_GEOMETRY, isBuiltInGeometry, sizeToRestore } from "./windowGeometry.js";

test("the first window keeps its size in CSS pixels on a scaled display", () => {
    // 870x654 physical pixels at 125% are 696x523 CSS pixels: under the 800px breakpoint.
    assert.deepEqual(sizeToRestore(BUILT_IN_GEOMETRY, 1.25), { width: 1088, height: 818 });
    assert.deepEqual(sizeToRestore(BUILT_IN_GEOMETRY, 1.5), { width: 1305, height: 981 });
    assert.deepEqual(sizeToRestore(BUILT_IN_GEOMETRY, 1), { width: 870, height: 654 });
    // The backend may send numbers as strings.
    assert.deepEqual(sizeToRestore({ x_pos: "0", y_pos: "0", width: "870", height: "654" }, 2), { width: 1740, height: 1308 });
});

test("a geometry the user has changed is restored as saved", () => {
    for (const saved of [
        { x_pos: 120, y_pos: 80, width: 870, height: 654 },
        { x_pos: 0, y_pos: 0, width: 1088, height: 818 },
        { x_pos: 0, y_pos: 0, width: 600, height: 400 },
    ]) {
        assert.equal(isBuiltInGeometry(saved), false);
        assert.deepEqual(sizeToRestore(saved, 1.5), { width: saved.width, height: saved.height });
    }
    // A scale factor that is missing or below 1 never shrinks the window.
    assert.deepEqual(sizeToRestore(BUILT_IN_GEOMETRY, undefined), { width: 870, height: 654 });
    assert.deepEqual(sizeToRestore(BUILT_IN_GEOMETRY, 0.5), { width: 870, height: 654 });
});

test("the built-in geometry is the backend's default", () => {
    const config = readFileSync(new URL("../../../src-python/config.py", import.meta.url), "utf8");
    const block = config.match(/self\._MAIN_WINDOW_GEOMETRY = \{([^}]+)\}/)[1];
    const backend = Object.fromEntries([...block.matchAll(/"(\w+)":\s*(-?\d+)/g)].map(([, key, value]) => [key, Number(value)]));
    assert.deepEqual(backend, BUILT_IN_GEOMETRY);
});
