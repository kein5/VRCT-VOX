import assert from "node:assert/strict";
import { test } from "node:test";
import { loadBridgeRoutes } from "./test/bridgeHarness.js";

test("compatible URL rejection restores the URL and settles only its pending request", async () => {
    const s = await loadBridgeRoutes();
    const url = s.stores.dynamicStoreRegistry.Atom_OpenAICompatibleURL;
    const key = s.stores.dynamicStoreRegistry.Atom_OpenAICompatibleAuthKey;
    const previousURL = "http://previous.invalid/v1";
    const previousKey = { state: "pending", data: "synthetic-saved-key" };
    s.runtime.store.set(url, { state: "pending", data: previousURL });
    s.runtime.store.set(key, previousKey);

    s.receiveRoutes({ status: 400, endpoint: "/set/data/openai_compatible_url", result: {
        error_code: "CONNECTION_OPENAI_COMPATIBLE_URL_INVALID",
        message: "The candidate has no supported models", data: previousURL,
    } });

    assert.deepEqual(s.runtime.store.get(url), { state: "ok", data: previousURL });
    assert.strictEqual(s.runtime.store.get(key), previousKey);
    assert.equal(s.notices.length, 1);
    assert.equal(s.notices[0].options.category_id, "CONNECTION_OPENAI_COMPATIBLE_URL_INVALID");
    assert.deepEqual(s.reads, []);
});

test("compatible key rejection still settles the key without altering the URL", async () => {
    const s = await loadBridgeRoutes();
    const url = s.stores.dynamicStoreRegistry.Atom_OpenAICompatibleURL;
    const key = s.stores.dynamicStoreRegistry.Atom_OpenAICompatibleAuthKey;
    const previousURL = { state: "pending", data: "http://previous.invalid/v1" };
    s.runtime.store.set(url, previousURL);
    s.runtime.store.set(key, { state: "pending", data: "synthetic-saved-key" });

    s.receiveRoutes({ status: 400, endpoint: "/set/data/openai_compatible_auth_key", result: {
        error_code: "AUTH_OPENAI_COMPATIBLE_FAILED", data: "synthetic-saved-key",
    } });

    assert.deepEqual(s.runtime.store.get(key), { state: "ok", data: "synthetic-saved-key" });
    assert.strictEqual(s.runtime.store.get(url), previousURL);
});
