import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import i18next from "i18next";
import yaml from "js-yaml";
import { hooks, loadModule, find, stubGlobals } from "../test/hookHarness.js";
import { loadBridgeStore } from "../test/bridgeHarness.js";

const resources = Object.fromEntries(["en", "ja", "ko"].map(language => [language, {
    translation: yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8")),
}]));
const icon = () => null;

for (const language of ["en", "ja", "ko"]) test(`${language}: recovery actions, stderr and splash use the selected locale with unchanged diagnostics`, async context => {
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, fallbackLng: "en", resources });
    const t = i18n.t.bind(i18n), translations = { useI18n: () => ({ t, i18n }) };
    for (const key of ["common_error.recovery_instructions", "common_error.copy_error_log", "common_error.updating",
        "common_error.update_now", "common_error.check_issues", "common_error.last_error_line", "common.check_latest_status",
        "main_page.backend_disconnected"]) {
        assert.equal(i18n.exists(key), true, key);
        assert.notEqual(t(key), key);
    }
    const runtime = hooks(), copies = [];
    stubGlobals(context, { window: { location: { origin: "http://localhost" } } });
    context.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
    let updating = false;
    const errorModule = await loadModule(new URL("../../views/app/others/error_boundary/AppErrorBoundary.jsx", import.meta.url), runtime, {
        "@useI18n": translations, "react-error-boundary": { ErrorBoundary: icon },
        "./contacts_container/ContactsContainer": { ContactsContainer: icon }, "@common_components": { CloseButton: icon },
        "@logics_common": { useWindow: () => ({ asyncCloseApp() {} }),
            useSoftwareVersion: () => ({ currentSoftwareVersion: { data: "test-version" }, currentLatestSoftwareVersionInfo: { data: { is_update_available: true } } }),
            useCopyToClipboard: () => ({ copyToClipboard: text => copies.push(text) }), useComputeMode: () => ({ currentComputeMode: { data: "cpu" } }),
            useUpdateSoftware: () => ({}), useIsSoftwareUpdating: () => ({ currentIsSoftwareUpdating: { data: updating } }) },
    });
    const boundary = runtime.render(errorModule.AppErrorBoundary, {});
    const error = { stack: "TypeError: untranslated diagnostic\n at component (app.js:20)" };
    const fallback = boundary.props.fallbackRender({ error });
    const tree = fallback.type(fallback.props);
    assert.ok(find(tree, node => node.props.children === t("common_error.recovery_instructions")));
    assert.match(t("common_error.recovery_instructions"), /VRCT-VOX/);
    const copy = find(tree, node => node.type === "button");
    assert.ok(find(copy, node => node.props.children === t("common_error.copy_error_log")));
    copy.props.onClick();
    assert.ok(copies[0].includes(error.stack));
    const safeActions = find(tree, node => node.type?.name === "SafeActionButtons");
    const actions = safeActions.type();
    assert.ok(find(actions.type(), node => node.props.children === t("common_error.check_issues")));
    assert.ok(find(actions.type(), node => node.props.children === t("common_error.update_now")));
    updating = true;
    assert.ok(find(actions.type(), node => node.props.children === t("common_error.updating")));

    const splashRuntime = hooks();
    const splash = await loadModule(new URL("../../views/app/others/splash_component/SplashComponent.jsx", import.meta.url), splashRuntime, {
        "@useI18n": translations, "@logics_common": { useWindow: () => ({}) }, "@common_components": { CloseButton: icon },
        "@ui_configs": { generateLocalizedDocumentUrl: () => ({ vrct_document_faq_url: "https://example.invalid/" }) },
        "./start_up_progress_container/StartUpProgressContainer": { StartUpProgressContainer: icon },
        "./download_models_container/DownloadModelsContainer": { DownloadModelsContainer: icon },
    });
    const announcement = find(splash.SplashComponent(), node => node.type?.name === "AnnouncementsContainer");
    for (const delay of [0, 15500, 4000, 4000]) {
        context.mock.timers.tick(delay);
        const node = splashRuntime.render(announcement.type);
        assert.ok(find(node, node => node.props.children === t("common.check_latest_status")));
    }

    const b = await loadBridgeStore(), notices = [];
    let handlers;
    b.stores.store.backend_session_owner = { attach: get => { handlers = get(); return () => {}; } };
    const controller = await loadModule(new URL("../../views/app/_app_controllers/StartPythonController.jsx", import.meta.url), b.runtime, {
        "@useI18n": translations, "@store": b.stores, "@utils": {},
        "@tauri-apps/api/core": {}, "@tauri-apps/plugin-shell": {}, "@useReceiveRoutes": { useReceiveRoutes: () => ({}) },
        "../../../logics/common/sidecarSession.js": {},
        "@logics_common": { useIsBackendReady: b.stores.useStore_IsBackendReady,
            useNotificationStatus: () => ({ showNotification_Error: text => notices.push(text) }) },
    });
    b.runtime.render(controller.StartPythonController);
    context.mock.method(console, "error", () => {});
    const line = "ImportError: unchanged diagnostics";
    handlers.stderr(line);
    assert.equal(notices[0], `${t("common_error.recovery_instructions")}\n${t("common_error.last_error_line")}: ${JSON.stringify(line)}`);
    for (const phase of ["failed", "stopped"]) {
        b.runtime.store.set(b.stores.Atom_IsBackendReady, { data: true, state: "ok" });
        handlers.setStartupState(phase);
        assert.equal(b.runtime.store.get(b.stores.Atom_IsBackendReady).data, false);
    }
    runtime.unmount(); splashRuntime.unmount(); b.runtime.unmount();
});
