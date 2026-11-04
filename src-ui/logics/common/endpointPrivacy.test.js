import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { endpointDescription, isNetworkDisconnected } from "./endpointPrivacy.js";

const t = key => key;
for (const [warning, urls] of [
    [true, [
        "http://10.0.0.1/v1", "http://172.16.0.1/v1", "http://172.31.255.254/v1",
        "http://192.168.1.1/v1", "http://169.254.1.1/v1",
        "http://[fc00::1]/v1", "http://[fdff::1]/v1", "http://[fe80::1]/v1", "http://[febf::1]/v1",
    ]],
    [false, [
        "http://127.0.0.1:1234/v1", "http://127.255.255.254/v1", "http://localhost:1234/v1",
        "http://LOCALHOST./v1", "http://[::1]/v1", "http://[0:0:0:0:0:0:0:1]/v1",
        "https://example.com/v1", "https://192.168.1.1/v1", "https://[fd00::1]/v1",
        "http://example.com/v1", "http://172.15.255.255/v1", "http://172.32.0.1/v1",
        "http://[fec0::1]/v1", "http://[2001:db8::1]/v1", "unfinished", "",
    ]],
]) for (const url of urls) test(`${url || "empty draft"}: LAN warning ${warning}, save notice retained`, () => {
    const description = endpointDescription(url, "models", t);
    assert.equal(description.includes("network_privacy.http_warning"), warning);
    assert.match(description, /network_privacy.save_notice/);
    assert.match(description, /^models /);
});

test("unknown connectivity does not incorrectly show the offline error", () => {
    for (const value of [null, undefined, true]) assert.equal(isNetworkDisconnected(value), false);
    assert.equal(isNetworkDisconnected(false), true);
});

test("all three URL settings use the draft warning and save bar", () => {
    const root = new URL("../../views/app/config_page/setting_section/setting_box/", import.meta.url);
    for (const file of ["translation/Translation.jsx", "transcription/Transcription.jsx"]) {
        const source = readFileSync(new URL(file, root), "utf8");
        assert.match(source, /desc=\{endpointDescription\(variable,/);
        assert.match(source, /saveFunction=\{saveFunction\}/);
        assert.match(source, /onChangeFunction=\{onChangeFunction\}/);
    }
});

test("URL errors restore the correct field and have actionable text in both locales", () => {
    const errors = readFileSync(new URL("../_useBackendErrorHandling.js", import.meta.url), "utf8");
    for (const [code, setter] of [
        ["CONNECTION_LMSTUDIO_URL_INVALID", "updateLMStudioURL"],
        ["CONNECTION_OPENAI_COMPATIBLE_URL_INVALID", "updateOpenAICompatibleURL"],
        ["CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID", "updateCustomWhisperURL"],
    ]) {
        const branch = errors.split(`case "${code}":`)[1].split("return;")[0];
        assert.ok(branch.includes(setter));
        assert.ok(branch.includes("showNotification_Error(localized"));
        for (const lang of ["en", "ja"]) {
            const locale = readFileSync(new URL(`../../../locales/${lang}.yml`, import.meta.url), "utf8");
            assert.match(locale, new RegExp(`${code}: .*HTTPS`));
            assert.match(locale, /http_warning:/);
            assert.match(locale, /save_notice:/);
        }
    }
});
