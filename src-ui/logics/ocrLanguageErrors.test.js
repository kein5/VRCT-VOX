import assert from "node:assert/strict";
import { test } from "node:test";
import { flush, loadBridgeRoutes } from "./test/bridgeHarness.js";

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

// Linux on Wayland: the user turned chat reading on, no window was found by name, and the desktop
// remembers the window shared before. It is shared again and chat reading is turned on once more.
const restoring = async (restored, wanted = true) => {
    const enabled = [], asked = [];
    const s = await loadBridgeRoutes(undefined, null, null, {
        configs: {
            ocrShouldRestoreSharedWindow: code => { asked.push(code); return wanted; },
            useOcrSharedWindow: () => ({ restore: async () => { if (restored instanceof Error) throw restored; return restored; } }),
        },
        main: { useMainFunction: () => ({ updateOcrCaptureStatus: () => {}, setOcrCapture: value => enabled.push(value) }) },
    });
    return { s, enabled, asked };
};
const windowNotFound = endpoint => ({ endpoint, status: 400, result: { error_code: "OCR_DISABLED_WINDOW_NOT_FOUND", data: false } });

test("a remembered window is shared again and chat reading turned on once more, without a notice", async () => {
    const { s, enabled, asked } = await restoring(true);
    s.receiveRoutes(windowNotFound("/set/enable/ocr_capture"));
    await flush();
    assert.deepEqual(asked, ["OCR_DISABLED_WINDOW_NOT_FOUND"]);
    assert.deepEqual(enabled, [true]);
    assert.deepEqual(s.notices, []);
});

for (const [name, outcome] of [["could not be shared", false], ["failed", new Error("screencast_failed")]]) {
    test(`when the remembered window ${name}, chat reading stays off and the usual notice is shown`, async () => {
        const { s, enabled } = await restoring(outcome);
        s.receiveRoutes(windowNotFound("/set/enable/ocr_capture"));
        await flush();
        assert.deepEqual(enabled, []);
        assert.equal(s.notices.length, 1);
        assert.equal(s.notices[0].options.category_id, "OCR_DISABLED_WINDOW_NOT_FOUND");
    });
}

test("nothing is shared again when there is no remembered window, or for a language change", async () => {
    const none = await restoring(true, false);
    none.s.receiveRoutes(windowNotFound("/set/enable/ocr_capture"));
    await flush();
    assert.deepEqual(none.enabled, []);
    assert.equal(none.s.notices.length, 1);

    const language = await restoring(true);
    language.s.receiveRoutes(windowNotFound("/set/data/ocr_source_language"));
    await flush();
    assert.deepEqual(language.asked, []);
    assert.deepEqual(language.enabled, []);
    assert.equal(language.s.notices.length, 1);
});
