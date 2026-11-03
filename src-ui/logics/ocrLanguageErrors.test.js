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
