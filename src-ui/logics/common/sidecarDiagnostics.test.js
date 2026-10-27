import assert from "node:assert/strict";
import { test } from "node:test";
import { isSidecarWarning } from "./sidecarDiagnostics.js";

test("structured Python warnings keep multiline messages out of fatal notifications", () => {
    assert.equal(isSidecarWarning(JSON.stringify({ type: "vrct_warning", category: "FutureWarning", message: "first\n次行", filename: "x.py", lineno: 4 })), true);
    assert.equal(isSidecarWarning("x.py:1: FutureWarning: legacy diagnostic"), true);
});

test("exceptions, malformed diagnostics and unknown stderr remain errors", () => {
    for (const line of ["Traceback (most recent call last):", "RuntimeError: failure", "RuntimeError: FutureWarning: failure", "{bad", '{"type":"vrct_warning"}', "driver failed", null]) {
        assert.equal(isSidecarWarning(line), false);
    }
});
