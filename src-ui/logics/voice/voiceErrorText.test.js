import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import i18next from "i18next";
import yaml from "js-yaml";
import { voiceErrorText } from "./voiceErrorText.js";

const resources = Object.fromEntries(["en", "ja"].map(language => [language, {
    translation: yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8")),
}]));

for (const language of ["en", "ja"]) test(`${language}: every code the voice pages explain is explained on the main screen too`, async () => {
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, fallbackLng: false, resources });
    const t = i18n.t.bind(i18n), exists = key => i18n.exists(key);
    const codes = Object.keys(resources[language].translation.voice.input_errors);
    assert.ok(codes.includes("vc_gpu_unavailable"));
    for (const code of codes) {
        const text = voiceErrorText(code, "RVC", t, exists);
        const key = exists(`voice_ui.errors.${code}`) ? `voice_ui.errors.${code}` : `voice.input_errors.${code}`;
        assert.equal(text, `${t(key)} (${code})`, code);
    }
    // voice_ui.errors wins where both have the code.
    assert.equal(voiceErrorText("voice_route_muted", "TTS", t, exists), `${t("voice_ui.errors.voice_route_muted")} (voice_route_muted)`);
});

test("an unknown code is shown as it is, with where to look", () => {
    const t = (key, values) => `${key}:${values?.page ?? ""}`;
    assert.equal(voiceErrorText("vc_new_failure", "RVC", t, () => false), "vc_new_failure · voice_ui.check_settings:RVC");
    // Free text is never looked up as a key.
    assert.equal(voiceErrorText("Some message.", "TTS", t, () => true), "Some message. · voice_ui.check_settings:TTS");
});
