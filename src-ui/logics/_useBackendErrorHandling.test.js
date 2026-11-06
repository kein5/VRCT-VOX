import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { renderToStaticMarkup } from "react-dom/server";
import { loadBridgeRoutes } from "./test/bridgeHarness.js";

test("credential reentry notices and field hints exist in every supported locale", () => {
    for (const language of ["en", "ja", "ko", "zh-Hans", "zh-Hant"]) {
        const locale = yaml.load(readFileSync(new URL(`../../locales/${language}.yml`, import.meta.url), "utf8"));
        assert.ok(locale.backend_errors.CREDENTIAL_REENTRY_REQUIRED);
        assert.ok(locale.config_page.common.credential_reentry_required);
    }
});

for (const [base, provider] of [["OpenAICompatible", "openai_compatible"], ["CustomWhisper", "custom_whisper"]]) {
    test(`${provider}: credential reentry settles only the URL and explains the rejection`, async () => {
        const s = await loadBridgeRoutes();
        const url = s.stores.dynamicStoreRegistry[`Atom_${base}URL`];
        const key = s.stores.dynamicStoreRegistry[`Atom_${base}AuthKey`];
        const savedURL = "https://previous.invalid/v1";
        const savedKey = { state: "pending", data: "synthetic-saved-key" };
        s.runtime.store.set(url, { state: "pending", data: savedURL });
        s.runtime.store.set(key, savedKey);
        s.receiveRoutes({ status: 400, endpoint: `/set/data/${provider}_url`, result: {
            error_code: "CREDENTIAL_REENTRY_REQUIRED", data: savedURL,
        } });
        assert.deepEqual(s.runtime.store.get(url), { state: "ok", data: savedURL });
        assert.strictEqual(s.runtime.store.get(key), savedKey);
        assert.equal(s.notices.length, 1);
        assert.equal(s.notices[0].options.category_id, "CREDENTIAL_REENTRY_REQUIRED");
        assert.deepEqual(s.reads, []);
    });
}

test("compatible URL rejection restores the URL and settles only its pending request", async () => {
    const s = await loadBridgeRoutes();
    const url = s.stores.dynamicStoreRegistry.Atom_OpenAICompatibleURL;
    const key = s.stores.dynamicStoreRegistry.Atom_OpenAICompatibleAuthKey;
    const previousURL = "https://previous.invalid/v1";
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
    const previousURL = { state: "pending", data: "https://previous.invalid/v1" };
    s.runtime.store.set(url, previousURL);
    s.runtime.store.set(key, { state: "pending", data: "synthetic-saved-key" });

    s.receiveRoutes({ status: 400, endpoint: "/set/data/openai_compatible_auth_key", result: {
        error_code: "AUTH_OPENAI_COMPATIBLE_FAILED", data: "synthetic-saved-key",
    } });

    assert.deepEqual(s.runtime.store.get(key), { state: "ok", data: "synthetic-saved-key" });
    assert.strictEqual(s.runtime.store.get(url), previousURL);
});

for (const [field, code] of [
    ["lmstudio_url", "CONNECTION_LMSTUDIO_URL_INVALID"],
    ["openai_compatible_url", "CONNECTION_OPENAI_COMPATIBLE_URL_INVALID"],
    ["transcription_custom_url", "CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID"],
    ["openai_compatible_url", "CREDENTIAL_REENTRY_REQUIRED"],
    ["custom_whisper_url", "CREDENTIAL_REENTRY_REQUIRED"],
]) test(`${field}: ${code} renders in the saved UI language`, async () => {
    const resources = Object.fromEntries(["en", "ja"].map(language => [language, {
        translation: yaml.load(readFileSync(new URL(`../../locales/${language}.yml`, import.meta.url), "utf8")),
    }]));
    const i18n = i18next.createInstance();
    await i18n.init({ lng: "en", resources });
    const s = await loadBridgeRoutes(undefined, i18n);
    s.receiveRoutes({ status: 400, endpoint: `/set/data/${field}`, result: {
        error_code: code, message: "The saved URL was invalid", data: "",
    } });
    const notice = s.notices.at(-1);
    assert.equal(notice.type, "error");
    assert.equal(notice.options.category_id, code);
    assert.equal(renderToStaticMarkup(notice.key), resources.en.translation.backend_errors[code]);

    // Settings finish applying after the IPC notice was already queued.
    await i18n.changeLanguage("ja");
    assert.equal(s.notices.length, 1);
    assert.equal(renderToStaticMarkup(notice.key), resources.ja.translation.backend_errors[code]);
});

test("other backend notifications still resolve their message when received", async () => {
    const i18n = i18next.createInstance();
    await i18n.init({ lng: "en", resources: {
        en: { translation: { backend_errors: { CONNECTION_LMSTUDIO_FAILED: "Connection failed" } } },
        ja: { translation: { backend_errors: { CONNECTION_LMSTUDIO_FAILED: "接続できませんでした" } } },
    } });
    const s = await loadBridgeRoutes(undefined, i18n);
    s.receiveRoutes({ status: 400, endpoint: "/run/check_lmstudio_connection", result: {
        error_code: "CONNECTION_LMSTUDIO_FAILED", message: "Connection failed",
    } });
    await i18n.changeLanguage("ja");
    assert.equal(s.notices.at(-1).key, "Connection failed");
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

for (const language of ["en", "ja"]) test(`${language}: overlay failure notifies and re-reads all output switches`, async () => {
    const translation = yaml.load(readFileSync(new URL(`../../locales/${language}.yml`, import.meta.url), "utf8"));
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, resources: { [language]: { translation } } });
    const s = await loadBridgeRoutes(undefined, i18n);
    s.receiveRoutes({ status: 400, endpoint: "/run/message_output_error", result: {
        error_code: "OVERLAY_RUNTIME_FAILED", data: { reason: "runtime" }, message: "private native exception",
    } });
    assert.deepEqual(s.notices, [{ type: "error", key: translation.backend_errors.OVERLAY_RUNTIME_FAILED,
        options: { category_id: "OVERLAY_RUNTIME_FAILED" } }]);
    assert.deepEqual(s.reads, ["/get/data/overlay_small_log", "/get/data/overlay_large_log", "/get/data/overlay_vr_panel"]);
});
