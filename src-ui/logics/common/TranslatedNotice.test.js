import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { hooks, loadModule } from "../test/hookHarness.js";

const resources = Object.fromEntries(["en", "ja"].map(language => [language,
    { translation: yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8")) }]));

const setup = async () => {
    const i18n = i18next.createInstance();
    // The app starts in English and applies the saved language once the engine has sent it.
    await i18n.init({ lng: "en", fallbackLng: "en", resources });
    const runtime = hooks();
    const translated = await loadModule(new URL("./TranslatedNotice.jsx", import.meta.url), runtime,
        { "@useI18n": { useI18n: () => ({ t: i18n.t.bind(i18n) }) } });
    const draw = notice => notice.type(notice.props);
    return { i18n, runtime, translated, draw };
};

test("a notice raised before the saved language is applied is drawn in that language", async () => {
    const s = await setup();
    const notice = s.runtime.api.createElement(s.translated.TranslatedNotice, { k: "common_warning.osc_query_remote_mic_stopped",
        labels: { sync: "config_page.others.vrc_mic_mute_sync.label", microphone: "main_page.transcription_send" } });
    assert.match(s.draw(notice), /^Messages go to another machine.*VRC Mic Mute Sync.*Voice2Chatbox/);
    await s.i18n.changeLanguage("ja");
    const text = s.draw(notice);
    assert.equal(text, resources.ja.translation.common_warning.osc_query_remote_mic_stopped
        .replaceAll("{{sync}}", "VRCマイクミュート同期").replaceAll("{{microphone}}", "マイク入力"));
    assert.doesNotMatch(text, /\{\{|Voice2Chatbox/);
});

test("the save notice and the missing model notice are translated when drawn", async () => {
    const s = await setup();
    let raised;
    const status = s.runtime.jotai.atom({ state: "ok", data: {} });
    const common = await loadModule(new URL("./useNotificationStatus.js", import.meta.url), s.runtime, {
        "@store": { useStore_NotificationStatus: () => ({ currentNotificationStatus: s.runtime.store.get(status),
            updateNotificationStatus: value => { raised = value; } }) },
        "react-toastify": { toast: { dismiss() {} } }, "./TranslatedNotice": s.translated,
    });
    s.runtime.render(common.useNotificationStatus).showNotification_SaveSuccess();
    await s.i18n.changeLanguage("ja");
    assert.equal(s.draw(raised.message), resources.ja.translation.config_page.notifications.save_success);

    const models = await loadModule(new URL("./useIsVrctAvailable.jsx", import.meta.url), s.runtime, {
        "@store": { useStore_IsVrctAvailable: () => ({ currentIsVrctAvailable: { data: true }, updateIsVrctAvailable() {} }) },
        "@logics_common": { useNotificationStatus: () => ({ showNotification_Warning: notice => { raised = notice; } }) },
        "./TranslatedNotice": s.translated,
    });
    s.runtime.render(models.useIsVrctAvailable).handleAiModelsAvailability(false);
    assert.equal(s.draw(raised), resources.ja.translation.runtime.local_models_unavailable);
});
