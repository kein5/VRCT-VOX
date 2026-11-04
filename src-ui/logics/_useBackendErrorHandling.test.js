import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
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

test("output failures have separate warnings per sink and never expose raw errors", async () => {
    const s = await loadBridgeRoutes();
    for (const output of ["osc", "logger", "tts", "raw private exception"]) {
        s.receiveRoutes({ status: 400, endpoint: "/run/message_output_error", result: {
            error_code: "MESSAGE_OUTPUT_FAILED", message: "raw private exception", data: { output },
        } });
    }
    assert.deepEqual(s.notices.map(notice => notice.options.category_id), [
        "MESSAGE_OUTPUT_FAILED.osc", "MESSAGE_OUTPUT_FAILED.logger", "MESSAGE_OUTPUT_FAILED.tts", "MESSAGE_OUTPUT_FAILED.unknown",
    ]);
    assert.ok(s.notices.every(notice => notice.type === "warning" && notice.key === "backend_errors.MESSAGE_OUTPUT_FAILED"));
    assert.deepEqual(s.reads, []);
});

for (const language of ["en", "ja"]) test(`${language}: partial output warning names the output and explains duplicate risk`, async () => {
    const translation = yaml.load(readFileSync(new URL(`../../locales/${language}.yml`, import.meta.url), "utf8"));
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, resources: { [language]: { translation } } });
    const s = await loadBridgeRoutes(undefined, i18n);
    for (const output of ["osc", "overlay_small", "overlay_large", "clipboard", "ui", "websocket", "logger", "history", "tts", "unknown"]) {
        assert.ok(i18n.exists(`message_outputs.${output}`));
        s.receiveRoutes({ status: 400, endpoint: "/run/message_output_error", result: {
            error_code: "MESSAGE_OUTPUT_FAILED", data: { output }, message: "raw error",
        } });
        const notice = s.notices.at(-1);
        assert.ok(notice.key.includes(i18n.t(`message_outputs.${output}`)));
        assert.match(notice.key, language === "ja" ? /再送すると、ほかの出力先に同じメッセージが重ねて届く/ : /If you resend it, those outputs may receive it twice/);
        assert.equal(notice.type, "warning");
    }
});
