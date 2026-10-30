import test from "node:test";
import assert from "node:assert/strict";
import { isRelayAllowed } from "./vrPanelWire.js";

test("model download catalog, state and mutations stay out of overlay relay", () => {
    for (const path of ["/get/data/model_download_catalog", "/get/data/model_download_state",
        "/get/data/model_download_hardware", "/run/refresh_model_download_hardware",
        "/run/start_model_download", "/run/cancel_model_download", "/run/apply_model_download"]) {
        assert.equal(isRelayAllowed(path), false, path);
    }
});
