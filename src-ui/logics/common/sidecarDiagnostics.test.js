import assert from "node:assert/strict";
import { test } from "node:test";
import { isSidecarWarning } from "./sidecarDiagnostics.js";

test("structured Python warnings keep multiline messages out of fatal notifications", () => {
    assert.equal(isSidecarWarning(JSON.stringify({ type: "vrct_warning", category: "FutureWarning", message: "first\n次行", filename: "x.py", lineno: 4 })), true);
    assert.equal(isSidecarWarning("x.py:1: FutureWarning: legacy diagnostic"), true);
});

test("ONNX Runtime's native warnings are not fatal, but its errors are", () => {
    const warning = "\u001b[0;93m2026-10-31 10:57:46.656522487 [W:onnxruntime:Default, device_discovery.cc:95 GetPciBusId] Skipping pci_bus_id for PCI path\u001b[m";
    assert.equal(isSidecarWarning(warning), true);
    assert.equal(isSidecarWarning("2026-10-31 10:57:46.656522487 [W:onnxruntime:, session_state.cc:1166 VerifyEachNodeIsAssignedToAnEp] note"), true);
    assert.equal(isSidecarWarning("2026-10-31 10:57:46.656522487 [E:onnxruntime:Default, provider_bridge.cc:1 Fn] failed"), false);
});

test("exceptions, malformed diagnostics and unknown stderr remain errors", () => {
    for (const line of ["Traceback (most recent call last):", "RuntimeError: failure", "RuntimeError: FutureWarning: failure", "{bad", '{"type":"vrct_warning"}', "driver failed", null]) {
        assert.equal(isSidecarWarning(line), false);
    }
});
