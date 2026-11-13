import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useStore_MessageLogs } from "@store";
import { useIsBackendReady } from "@logics_common";
import { useAppearance, useVr } from "@logics_configs";
import { captionLines, stampLines } from "../../../logics/captionOverlay/lines";

// Captions over the desktop: opens the overlay window while the setting is on
// and hands it the last rows of the message log. The window only draws; what
// it shows and for how long is decided here.
export const CaptionOverlayController = () => {
    const { currentIsEnabledOverlayDesktop, currentOverlayDesktopSettings, currentOverlayShowOnlyTranslatedMessages } = useVr();
    const { currentMessageLogs } = useStore_MessageLogs();
    const { currentSelectedFontFamily } = useAppearance();
    const { currentIsBackendReady } = useIsBackendReady();
    const [supported, setSupported] = useState(false);
    const stamps = useRef(null);

    useEffect(() => {
        let disposed = false;
        invoke("caption_overlay_supported").then(value => { if (!disposed) setSupported(value === true); }, () => {});
        return () => { disposed = true; };
    }, []);

    const enabled = supported && currentIsBackendReady.data === true && currentIsEnabledOverlayDesktop.data === true;
    const settings = currentOverlayDesktopSettings.data;

    useEffect(() => {
        if (!supported) return;
        invoke("caption_overlay_set", { open: enabled, position: settings.position })
            .catch(error => console.error("Caption overlay window could not be changed", error));
    }, [supported, enabled, settings.position]);

    useEffect(() => {
        if (!enabled) {
            stamps.current = null;
            return;
        }
        const lines = captionLines(currentMessageLogs.data, { onlyTranslated: currentOverlayShowOnlyTranslatedMessages.data === true });
        stamps.current = stampLines(stamps.current, lines, Date.now(), settings.display_duration * 1000);
        invoke("caption_overlay_update", { snapshot: {
            lines: lines.map(line => ({ ...line, until: stamps.current.get(line.id).until })),
            position: settings.position, font_size: settings.font_size, opacity: settings.opacity,
            font_family: currentSelectedFontFamily.data,
        } }).catch(error => console.error("Caption overlay could not be updated", error));
    }, [enabled, currentMessageLogs.data, currentOverlayShowOnlyTranslatedMessages.data, settings.position,
        settings.font_size, settings.opacity, settings.display_duration, currentSelectedFontFamily.data]);

    return null;
};
