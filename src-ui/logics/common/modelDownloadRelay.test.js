import test from "node:test";
import assert from "node:assert/strict";
import { isRelayAllowed } from "./vrPanelWire.js";

test("model download catalog, state and mutations stay out of overlay relay", () => {
    for (const path of ["/get/data/model_download_catalog", "/get/data/model_download_state",
        "/get/data/model_download_hardware", "/run/refresh_model_download_hardware",
        "/run/start_model_download", "/run/cancel_model_download", "/run/apply_model_download",
        "/get/data/vc_runtime_catalog", "/get/data/vc_runtime_state",
        "/run/start_vc_runtime_setup", "/run/cancel_vc_runtime_setup"]) {
        assert.equal(isRelayAllowed(path), false, path);
    }
});
