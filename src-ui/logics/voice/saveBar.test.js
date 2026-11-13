import assert from "node:assert/strict";
import { test } from "node:test";
import { changedPaths } from "./saveBar.js";

test("only the edited leaves of nested settings are reported", () => {
    const saved = { mode: "translated", profiles: { japanese: { model: "/a.gguf", device: "auto" }, asr: { model: "" } } };
    const draft = { mode: "translated", profiles: { japanese: { model: "/b.gguf", device: "auto" }, asr: { model: "" } } };
    assert.deepEqual(changedPaths(saved, draft), [["profiles", "japanese", "model"]]);
});

test("unchanged settings report nothing and a replaced value is one change", () => {
    assert.deepEqual(changedPaths({ a: 1, b: [1, 2] }, { a: 1, b: [1, 2] }), []);
    assert.deepEqual(changedPaths({ b: [1, 2] }, { b: [2] }), [["b"]]);
    assert.deepEqual(changedPaths({ a: 1 }, { a: 1, c: true }), [["c"]]);
});
