import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { loadModule } from "../test/hookHarness.js";
import { loadBridgeStore, loadBridgeRoutes } from "../test/bridgeHarness.js";

for (const language of ["en", "ja"]) {
    const translation = yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
    test(`${language}: OSCQuery is unavailable until setup succeeds, and failures notify`, async () => {
        const i18n = i18next.createInstance();
        await i18n.init({ lng: language, resources: { [language]: { translation } } });
        const { runtime, stores } = await loadBridgeStore();
        const notices = [];
        const subject = await loadModule(new URL("./useHandleOscQuery.js", import.meta.url), runtime, {
            "@useI18n": { useI18n: () => ({ t: i18n.t.bind(i18n) }) },
            "@logics_common": {
                useIsOscAvailable: stores.useStore_IsOscAvailable,
                useNotificationStatus: () => ({ showNotification_Warning: (...args) => notices.push(args) }),
            },
        });
        const { handleOscQuery } = runtime.render(subject.useHandleOscQuery);
        assert.equal(runtime.store.get(stores.Atom_IsOscAvailable).data, false);
        handleOscQuery({ data: true, disabled_functions: [] });
        assert.equal(runtime.store.get(stores.Atom_IsOscAvailable).data, true);
        handleOscQuery({ data: false, disabled_functions: ["vrc_mic_mute_sync"] });
        assert.equal(runtime.store.get(stores.Atom_IsOscAvailable).data, false);
        assert.deepEqual(notices, [[`${i18n.t("common_warning.unable_to_use_osc_query")}\n- ${i18n.t("config_page.others.vrc_mic_mute_sync.label")}`, { hide_duration: 10000 }]]);
        assert.equal(i18n.exists("config_page.common.warning_labels.unable_to_use_osc_query"), true);
        // Started with another machine as the destination and nothing switched
        // off: unavailable, but no warning (the setting's row says why).
        handleOscQuery({ data: true, disabled_functions: [] });
        handleOscQuery({ data: false, disabled_functions: [] });
        assert.equal(runtime.store.get(stores.Atom_IsOscAvailable).data, false);
        assert.equal(notices.length, 1);
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
