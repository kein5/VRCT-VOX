import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { hooks, loadModule, find, stubGlobals } from "../../../logics/test/hookHarness.js";

for (const language of ["en", "ja"]) {
    test(`${language}: close icon has a localized default, precise overrides and no SVG name`, async () => {
        const translations = i18next.createInstance();
        const resource = yaml.load(readFileSync(new URL(`../../../../locales/${language}.yml`, import.meta.url), "utf8"));
        await translations.init({ lng: language, resources: { [language]: { translation: resource } } });
        const runtime = hooks();
        const { CloseButton } = await loadModule(new URL("./CloseButton.jsx", import.meta.url), runtime, {
            "@useI18n": { useI18n: () => ({ t: translations.t.bind(translations) }) },
        });
        let clicks = 0;
        const render = props => runtime.render(CloseButton, { onClick: () => clicks++, ...props });
        const button = render();
        assert.equal(button.type, "button");
        assert.equal(button.props.type, "button", "closing must never submit an enclosing form");
        assert.equal(button.props["aria-label"], language === "ja" ? "閉じる" : "Close");
        const icon = find(button, node => typeof node.type === "function");
        assert.equal(icon.props["aria-hidden"], "true");
        assert.equal(icon.props.focusable, "false");
        for (const key of ["common.dismiss_notification", "studio.close"]) {
            assert.equal(translations.exists(key), true, key);
            assert.equal(render({ "aria-label": translations.t(key) }).props["aria-label"], translations.t(key));
        }
        button.props.onClick();
        assert.equal(clicks, 1);
    });
}

test("splash, startup failure and error fallback name the close-application action", async () => {
    for (const name of ["SplashComponent", "StartupFailedComponent", "AppErrorBoundary"]) {
        const runtime = hooks();
        let closed = 0;
        const common = { useWindow: () => ({ asyncCloseApp: () => closed++ }),
            useSoftwareVersion: () => ({ currentSoftwareVersion: { data: "test" } }),
            useCopyToClipboard: () => ({ is_copied: false }) };
        const directory = name === "AppErrorBoundary" ? "error_boundary" : "splash_component";
        const exports = await loadModule(new URL(`../../app/others/${directory}/${name}.jsx`, import.meta.url), runtime, {
            "@common_components": { CloseButton: "close-button" }, "@logics_common": common,
            "@ui_configs": {},
            "./start_up_progress_container/StartUpProgressContainer": { StartUpProgressContainer: "progress" },
            "./download_models_container/DownloadModelsContainer": { DownloadModelsContainer: "downloads" },
            "../../../../logics/common/useBackendStartup": { useBackendStartup: () => ({ retryStartup: () => {} }) },
            "react-error-boundary": { ErrorBoundary: "error-boundary" },
            "./contacts_container/ContactsContainer": { ContactsContainer: "contacts" },
        });
        let tree = runtime.render(exports[name], {});
        if (name === "AppErrorBoundary") {
            const fallback = tree.props.fallbackRender({ error: null });
            tree = runtime.render(fallback.type, fallback.props);
        }
        const close = find(tree, node => node.type === "close-button");
        assert.equal(close.props["aria-label"], "studio.close", name);
        close.props.onClick();
        assert.equal(closed, 1);
        runtime.unmount();
    }
});

test("notification close names dismissal and retains its toast callback", async context => {
    const runtime = hooks();
    let options, dismissed = 0;
    stubGlobals(context, { setTimeout: callback => { callback(); } });
    const notification = runtime.jotai.atom({ state: "ok", data: { is_open: true, status: "info", message: "notice" } });
    const { SnackbarController } = await loadModule(new URL("../../app/others/snackbar_controller/SnackbarController.jsx", import.meta.url), runtime, {
        "@common_components": { CloseButton: "close-button" },
        "./ReactToastifyOverrideClass.scss": {},
        "react-toastify": { ToastContainer: "toasts", cssTransition: () => ({}), toast: (_, value) => { options = value; } },
        "@store": { Atom_NotificationStatus: notification },
        "@logics_common": { useNotificationStatus: () => ({ closeNotification: () => {} }) },
    });
    runtime.render(SnackbarController);
    const button = options.closeButton({ closeToast: () => dismissed++ });
    assert.equal(button.props["aria-label"], "common.dismiss_notification");
    button.props.onClick();
    assert.equal(dismissed, 1);
    runtime.unmount();
});
