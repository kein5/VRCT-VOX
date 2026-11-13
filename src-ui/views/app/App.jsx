import { TranscriptionConsentController } from "./_app_controllers/TranscriptionConsentController";
import { TranslationSetupController } from "./_app_controllers/TranslationSetupController";
import { TelemetryNoticeController } from "./_app_controllers/TelemetryNoticeController";
import { useI18n } from "@useI18n";
import { useRef } from "react";

import {
    KeyEventController,
    StartPythonController,
    GlobalHotKeyController,
    UiLanguageController,
    ConfigPageCloseTriggerController,
    UiSizeController,
    FontFamilyController,
    TransparencyController,
    CornerRadiusController,
    VrPanelSyncController,
    OcrSharedWindowController,
} from "./_app_controllers";

import styles from "./App.module.scss";

import { MainPage } from "./main_page/MainPage";
import { QuickChatController } from "./_app_controllers/QuickChatController";
import { CaptionOverlayController } from "./_app_controllers/CaptionOverlayController";
import { ConfigPage } from "./config_page/ConfigPage";

import {
    WindowTitleBar,
    SplashComponent,
    UpdatingComponent,
    ModalController,
    SnackbarController,
    AppErrorBoundary,
} from "./others";

import { useIsBackendReady, useIsSoftwareUpdating, WindowGeometryController, WindowCloseController } from "@logics_common";
import { useBackendStartup } from "../../logics/common/useBackendStartup";
import { StartupFailedComponent } from "./others/splash_component/StartupFailedComponent";

export const App = () => {
    const { currentIsBackendReady } = useIsBackendReady();
    const { startupState } = useBackendStartup();
    const { i18n } = useI18n();

    return (
        <div className={styles.container}>
            <AppErrorBoundary >
                <KeyEventController />
                <StartPythonController />
                <WindowCloseController />
                <GlobalHotKeyController />
                <QuickChatController />
                <CaptionOverlayController />
                <UiLanguageController />
                <ConfigPageCloseTriggerController />
                <UiSizeController />
                <FontFamilyController />
                <TransparencyController />
                <CornerRadiusController />
                <VrPanelSyncController />
                <OcrSharedWindowController />

                {startupState === "failed"
                    ? <StartupFailedComponent />
                    : startupState !== "stopped" && currentIsBackendReady.data === false
                    ? <SplashComponent />
                    : <Contents key={i18n.language} />
                }

                <SnackbarController />
            </AppErrorBoundary>
        </div>
    );
};

const Contents = () => {
    const { currentIsSoftwareUpdating } = useIsSoftwareUpdating();
    const mainPage = useRef(null);
    return (
        <>
            <WindowGeometryController />

            <WindowTitleBar />
            {currentIsSoftwareUpdating.data === false
            ?
            <div className={styles.pages_wrapper}>
                <ConfigPage />
                <MainPage focusFallback={mainPage} />
                <ModalController fallback={mainPage} />
                <TranscriptionConsentController />
                <TranslationSetupController />
                <TelemetryNoticeController />
            </div>
            :
            <UpdatingComponent />
            }
        </>
    );
};
