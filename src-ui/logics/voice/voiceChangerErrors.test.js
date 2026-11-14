import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import i18next from "i18next";
import yaml from "js-yaml";

// The voice changer reports why it could not start as a code. Each code it can send says, in
// both languages, what went wrong and what to do (voice.input_errors; the main screen's notice falls
// back to it, voiceErrorText.js). An unknown code would be shown as is.
// The codes that reach the screen (src-python/models/voice_conversion: direct_voice.py, process.py,
// isolated.py, protocol.py WORKER_FAILURES) and had no message.
const CODES = ["vc_start_failed", "vc_engine_unavailable", "source_bridge_stopping", "vc_worker_failed",
    "vc_model_missing", "vc_runtime_version_unsupported", "vc_checkpoint_incomplete", "vc_index_failed",
    "vc_engine_format_invalid", "vc_router_timeout", "vc_router_failed", "vc_cleanup_failed", "vc_ready_invalid"];
const resources = Object.fromEntries(["en", "ja"].map(language => [language, {
    translation: yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8")),
}]));

for (const language of ["en", "ja"]) test(`${language}: voice changer errors say what to do`, async () => {
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, fallbackLng: false, resources });
    for (const code of CODES) for (const key of [`voice.input_errors.${code}`]) {
        assert.equal(i18n.exists(key), true, key);
        const text = i18n.t(key);
        assert.notEqual(text, code, key);
        assert.ok(text.length > 20, key);
    }
});
