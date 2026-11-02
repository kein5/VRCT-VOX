import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import yaml from "js-yaml";
import { CLOUD_TRANSCRIPTION_ENGINES } from "./cloudTranscription.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const setter = read("./config_page_setter/ui_config_setter.js");
const mainloop = read("../../../src-python/mainloop.py");

// Base_Name -> base_endpoint_name for every generated setting.
const settings = Object.fromEntries([...setter.matchAll(/Base_Name: "(\w+)",[^{}]*?base_endpoint_name: "(\w+)"/gs)]
    .map(([, base, endpoint]) => [base, endpoint]));

test("each cloud engine's settings reach backend endpoints that exist", () => {
    for (const { base, key, has_url } of CLOUD_TRANSCRIPTION_ENGINES) {
        const expected = {
            [`${base}AuthKey`]: `${key}_auth_key`,
            [`Selectable${base}ModelList`]: `selectable_${key}_model_list`,
            [`Selected${base}Model`]: `selected_${key}_model`,
            ...(has_url ? { [`${base}URL`]: `${key}_url` } : {}),
        };
        for (const [setting, endpoint] of Object.entries(expected)) {
            assert.equal(settings[setting], endpoint, `${setting} should use ${endpoint}`);
            assert.ok(mainloop.includes(`"/get/data/${endpoint}"`), `backend has no /get/data/${endpoint}`);
        }
    }
    assert.equal(settings.SelectableTranscriptionEngines, "selectable_transcription_engines");
});

test("each cloud engine id is one the backend knows", () => {
    const providers = read("../../../src-python/models/transcription/transcription_openai_compatible.py");
    for (const { id } of CLOUD_TRANSCRIPTION_ENGINES) {
        assert.ok(id === "Deepgram" || providers.includes(`"${id}"`), `unknown engine ${id}`);
    }
});

for (const language of ["en", "ja"]) {
    test(`${language}: every cloud engine has its labels`, () => {
        const transcription = yaml.load(read(`../../../locales/${language}.yml`)).config_page.transcription;
        assert.ok(transcription.select_transcription_engine.desc);
        assert.ok(transcription.cloud_section.label && transcription.cloud_section.desc);
        for (const { key, has_url } of CLOUD_TRANSCRIPTION_ENGINES) {
            assert.ok(transcription.select_transcription_engine.engines[key], `${language}: engine label ${key}`);
            assert.ok(transcription[`${key}_auth_key`]?.label, `${language}: ${key}_auth_key.label`);
            assert.ok(transcription[`select_${key}_model`]?.label, `${language}: select_${key}_model.label`);
            if (has_url) assert.ok(transcription[`${key}_url`]?.label, `${language}: ${key}_url.label`);
        }
    });
}
