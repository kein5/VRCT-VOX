import { invoke } from "@tauri-apps/api/core";
import { Command } from "@tauri-apps/plugin-shell";
import { useEffect, useRef } from "react";

import { useStdoutToPython } from "@useStdoutToPython";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { store, useStore_SelectableFontFamilyList, useStore_BackendStartupState, useStore_InitProgress } from "@store";
import { arrayToObject } from "@utils";
import { createSidecarSessionOwner } from "../../../logics/common/sidecarSession.js";
import { useI18n } from "@useI18n";
import { useNotificationStatus, useIsBackendReady } from "@logics_common";

export const StartPythonController = () => {
    const { t } = useI18n();
    const { receiveRoutes, backendStopped } = useReceiveRoutes();
    const { showNotification_Error } = useNotificationStatus();
    const { updateIsBackendReady } = useIsBackendReady();
    const { updateBackendStartupState } = useStore_BackendStartupState();
    const { updateInitProgress } = useStore_InitProgress();
    const { asyncFetchFonts } = useAsyncFetchFonts();
    const { asyncStdoutToPython } = useStdoutToPython();
    const handlersRef = useRef(null);
    handlersRef.current = {
        receiveRoutes,
        backendStopped,
        feedWatchdog: () => asyncStdoutToPython("/run/feed_watchdog"),
        beginStartup: () => {
            updateIsBackendReady(false);
            updateInitProgress(0);
        },
        setStartupState: phase => {
            updateBackendStartupState(phase);
            if (phase === "failed") updateIsBackendReady(false);
        },
        started: asyncFetchFonts,
        unexpectedExit: ({ code, signal }) => {
            console.error("sidecar exited", { code, signal });
            showNotification_Error(t("common_error.backend_stopped", { code: code ?? signal ?? "?" }),
                { hide_duration: null, category_id: "backend_stopped" });
        },
        stderr: line => {
            showNotification_Error(
                `An error occurred. Please restart VRCT-VOX or contact the developers. The last line:${JSON.stringify(line)}`, { hide_duration: null }
            );
            console.error("stderr", line);
        },
    };

    useEffect(() => {
        store.backend_session_owner ??= createSidecarSessionOwner({
            store,
            createCommand: () => Command.sidecar("bin/vrct-vox-sidecar"),
            setInterval,
            clearInterval,
        });
        // StrictMode replay and genuine remounts attach to the same session.
        // Detach stops its timer only when the last controller leaves; a late
        // spawn cannot install a timer while no controller is mounted.
        return store.backend_session_owner.attach(() => handlersRef.current);
    }, []);

    return null;
};

const useAsyncFetchFonts = () => {
    const { updateSelectableFontFamilyList } = useStore_SelectableFontFamilyList();
    const asyncFetchFonts = async (isCurrent) => {
        try {
            let fonts = await invoke("get_font_list");
            if (!isCurrent()) return;
            fonts = fonts.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
            updateSelectableFontFamilyList(arrayToObject(fonts));
        } catch (error) {
            if (isCurrent()) console.error("Error fetching fonts:", error);
        }
    };
    return { asyncFetchFonts };
};
