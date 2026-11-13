import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { loadModule } from "../test/hookHarness.js";
import { loadBridgeStore, loadBridgeRoutes } from "../test/bridgeHarness.js";

for (const language of ["en", "ja"]) {
    const translation = yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
    test(`${language}: OSCQuery is unavailable until setup succeeds, and each warning says what happened`, async () => {
        const i18n = i18next.createInstance();
        await i18n.init({ lng: language, resources: { [language]: { translation } } });
        const { runtime, stores } = await loadBridgeStore();
        const notices = [];
        const useI18n = { useI18n: () => ({ t: i18n.t.bind(i18n) }) };
        const subject = await loadModule(new URL("./useHandleOscQuery.js", import.meta.url), runtime, {
            "./TranslatedNotice": await loadModule(new URL("./TranslatedNotice.jsx", import.meta.url), runtime, { "@useI18n": useI18n }),
            "@logics_common": {
                useIsOscAvailable: () => ({ ...stores.useStore_IsOscAvailable(), ...stores.useStore_OscUnavailableReason() }),
                // The text is chosen when the notice is drawn: startup notices arrive
                // before the saved UI language is applied.
                useNotificationStatus: () => ({ showNotification_Warning: (notice, options) =>
                    notices.push([notice.type(notice.props), options]) }),
            },
        });
        const { handleOscQuery } = runtime.render(subject.useHandleOscQuery);
        const available = () => runtime.store.get(stores.Atom_IsOscAvailable).data;
        const reason = () => runtime.store.get(stores.Atom_OscUnavailableReason).data;
        const names = { sync: i18n.t("config_page.others.vrc_mic_mute_sync.label"),
            microphone: i18n.t("main_page.transcription_send"), settings: i18n.t("config_page.side_menu_labels.advanced_settings") };
        assert.equal(available(), false);
        handleOscQuery({ data: true, disabled_functions: [] });
        assert.deepEqual([available(), reason()], [true, null]);

        const cases = [
            ["setup_failed", true, "osc_query_failed_mic_stopped"],
            ["setup_failed", false, "osc_query_failed"],
            ["remote_destination", true, "osc_query_remote_mic_stopped"],
            ["remote_destination", false, "osc_query_remote"],
        ];
        for (const [why, microphone_stopped, key] of cases) {
            notices.length = 0;
            handleOscQuery({ data: false, disabled_functions: ["vrc_mic_mute_sync"], reason: why, microphone_stopped });
            assert.deepEqual([available(), reason()], [false, why]);
            const text = i18n.t(`common_warning.${key}`, names);
            assert.deepEqual(notices, [[text, { hide_duration: 10000, category_id: `common_warning.${key}` }]]);
            // The names of the switch and the tab are the ones on screen, and nothing is left unfilled.
            assert.ok(text.includes(names.sync) && !text.includes("{{"), text);
            assert.equal(text.includes(names.microphone), microphone_stopped, text);
            assert.equal(text.includes(names.settings), why === "setup_failed", text);
        }

        // Started with another machine as the destination and nothing switched
        // off: unavailable, with the reason for the setting's row, but no warning.
        notices.length = 0;
        handleOscQuery({ data: true, disabled_functions: [] });
        handleOscQuery({ data: false, disabled_functions: [], reason: "remote_destination", microphone_stopped: false });
        assert.deepEqual([available(), reason()], [false, "remote_destination"]);
        assert.equal(notices.length, 0);
        // A backend that sends no reason is treated as a failed setup.
        handleOscQuery({ data: false, disabled_functions: ["vrc_mic_mute_sync"] });
        assert.equal(reason(), "setup_failed");
        assert.deepEqual(notices, [[i18n.t("common_warning.osc_query_failed", names),
            { hide_duration: 10000, category_id: "common_warning.osc_query_failed" }]]);
    });

    test(`${language}: the mute sync row explains the reason it is unavailable`, async () => {
        const i18n = i18next.createInstance();
        await i18n.init({ lng: language, resources: { [language]: { translation } } });
        const { runtime, stores } = await loadBridgeStore();
        const subject = await loadModule(new URL("./useIsOscAvailable.js", import.meta.url), runtime, { "@store": stores });
        assert.equal(subject.oscUnavailableLabelKey("remote_destination"), "config_page.common.warning_labels.unable_to_use_osc_query_remote");
        for (const why of ["setup_failed", null, undefined])
            assert.equal(subject.oscUnavailableLabelKey(why), "config_page.common.warning_labels.unable_to_use_osc_query");
        for (const why of ["remote_destination", "setup_failed"]) assert.equal(i18n.exists(subject.oscUnavailableLabelKey(why)), true);
        runtime.store.set(stores.Atom_OscUnavailableReason, { state: "ok", data: "remote_destination" });
        assert.equal(runtime.render(subject.useIsOscAvailable).oscUnavailableLabelKey,
            "config_page.common.warning_labels.unable_to_use_osc_query_remote");
    });

    test(`${language}: rejected mute sync uses the existing localized error protocol`, async context => {
        context.mock.method(console, "error", () => {});
        const i18n = i18next.createInstance();
        await i18n.init({ lng: language, resources: { [language]: { translation } } });
        const s = await loadBridgeRoutes(undefined, i18n);
        s.receiveRoutes({ endpoint: "/set/enable/vrc_mic_mute_sync", status: 400,
            result: { error_code: "VRC_MIC_MUTE_SYNC_OSC_DISABLED", data: false } });
        assert.deepEqual(s.notices, [{ type: "error", key: i18n.t("backend_errors.VRC_MIC_MUTE_SYNC_OSC_DISABLED"),
            options: { category_id: "VRC_MIC_MUTE_SYNC_OSC_DISABLED" } }]);
    });
}
