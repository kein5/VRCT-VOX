import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import i18next from "i18next";
import yaml from "js-yaml";

const resources = Object.fromEntries(["en", "ja", "ko"].map(language => [language, {
    translation: yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8")),
}]));

for (const language of ["en", "ja", "ko"]) {
    test(`${language}: consent and existing telemetry controls resolve readable translations`, async () => {
        const translations = i18next.createInstance();
        await translations.init({ lng: language, fallbackLng: "en", resources });
        for (const path of ["auto_download_models.label", "auto_download_models.desc",
            "telemetry.label", "telemetry.desc", "telemetry.aptabase_privacy_policy_label"]) {
            const key = `config_page.others.${path}`;
            assert.equal(translations.exists(key), true, `missing ${language}: ${key}`);
            assert.equal(typeof translations.t(key), "string");
            assert.notEqual(translations.t(key), key);
            assert.ok(translations.t(key).trim().length > 0);
        }
    });
}
