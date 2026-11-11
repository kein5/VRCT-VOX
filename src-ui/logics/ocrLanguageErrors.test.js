import assert from "node:assert/strict";
import { test } from "node:test";
import { loadBridgeRoutes } from "./test/bridgeHarness.js";

for (const error_code of ["OCR_DISABLED_MODEL_MISSING", "OCR_DISABLED_MODEL_LOAD_FAILED"]) {
    test(`OCR language ${error_code} settles the previous language`, async () => {
        const s = await loadBridgeRoutes();
        const language = s.stores.dynamicStoreRegistry.Atom_OcrSourceLanguage;
        s.runtime.store.set(language, { state: "pending", data: "auto" });
        s.receiveRoutes({ endpoint: "/set/data/ocr_source_language", status: 400,
            result: { error_code, data: "auto" } });
        assert.equal(s.runtime.store.get(language).data, "auto");
        assert.equal(s.runtime.store.get(language).state, "ok");
        assert.equal(s.notices.length, 1);
        assert.equal(s.notices[0].type, "error");
        assert.equal(s.notices[0].options.category_id, error_code);
        assert.deepEqual(s.reads, []);
    });
}

// Linux on Wayland: a native Wayland window exists but cannot be found by name, so the notice says how to share it.
for (const [supported, key] of [[true, "common_error.ocr_window_not_found_wayland"], [false, "common_error.ocr_window_not_found"],
    [null, "common_error.ocr_window_not_found"]]) {
    test(`window not found names sharing only where a window can be shared (${supported})`, async () => {
        const s = await loadBridgeRoutes();
        s.runtime.store.set(s.stores.Atom_OcrSharedWindow, { state: "ok", data: { supported, active: false, busy: false, error: null } });
        s.receiveRoutes({ endpoint: "/set/enable/ocr_capture", status: 400,
            result: { error_code: "OCR_DISABLED_WINDOW_NOT_FOUND", data: false } });
        assert.equal(s.notices.length, 1);
        assert.equal(s.notices[0].key, key);
        assert.equal(s.stores.Atom_OcrCaptureStatus && s.runtime.store.get(s.stores.Atom_OcrCaptureStatus).data, false);
    });
}

test("a capture failure keeps its own notice on Wayland", async () => {
    const s = await loadBridgeRoutes();
    s.runtime.store.set(s.stores.Atom_OcrSharedWindow, { state: "ok", data: { supported: true, active: false, busy: false, error: null } });
    s.receiveRoutes({ endpoint: "/set/enable/ocr_capture", status: 400,
        result: { error_code: "OCR_DISABLED_CAPTURE_UNAVAILABLE", data: false } });
    assert.equal(s.notices[0].key, "common_error.ocr_capture_unavailable");
});
