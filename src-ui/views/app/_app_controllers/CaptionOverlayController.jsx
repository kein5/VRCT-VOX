import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useStore_MessageLogs } from "@store";
import { useI18n } from "@useI18n";
import { useIsBackendReady } from "@logics_common";
import { useAppearance, useVr } from "@logics_configs";
import { captionLines, stampLines } from "../../../logics/captionOverlay/lines";
import { useIoFlow } from "../../../logics/flow/useIoFlow";
import { overlayCount } from "../../../logics/flow/ioFlow.js";
import { flowNote, stripItems } from "../../../logics/flow/flowText.js";

// Captions over the desktop: opens the overlay window while the setting is on
// and hands it the last rows of the message log. The window only draws; what
// it shows and for how long is decided here. The flow strip (where the user's
// latest inputs went, in ms) shares the window and can be on without captions.
export const CaptionOverlayController = () => {
    const { t } = useI18n();
    const { currentIsEnabledOverlayDesktop, currentOverlayDesktopSettings, currentOverlayShowOnlyTranslatedMessages,
        currentIoFlowOverlaySettings } = useVr();
    const { currentMessageLogs } = useStore_MessageLogs();
    const { currentSelectedFontFamily } = useAppearance();
    const { currentIsBackendReady } = useIsBackendReady();
    const { currentIoFlow, currentIoTraces } = useIoFlow();
    const [supported, setSupported] = useState(false);
    const stamps = useRef(null);

    useEffect(() => {
        let disposed = false;
        invoke("caption_overlay_supported").then(value => { if (!disposed) setSupported(value === true); }, () => {});
        return () => { disposed = true; };
    }, []);

    const ready = supported && currentIsBackendReady.data === true;
    const captions = ready && currentIsEnabledOverlayDesktop.data === true;
    const flowShown = ready && currentIoFlowOverlaySettings.data?.desktop === true;
    const enabled = captions || flowShown;
    const settings = currentOverlayDesktopSettings.data;
    const count = overlayCount(currentIoFlowOverlaySettings.data);

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
        const lines = captions
            ? captionLines(currentMessageLogs.data, { onlyTranslated: currentOverlayShowOnlyTranslatedMessages.data === true })
            : [];
        stamps.current = stampLines(stamps.current, lines, Date.now(), settings.display_duration * 1000);
        invoke("caption_overlay_update", { snapshot: {
            lines: lines.map(line => ({ ...line, until: stamps.current.get(line.id).until })),
            position: settings.position, font_size: settings.font_size, opacity: settings.opacity,
            font_family: currentSelectedFontFamily.data,
            ...(flowShown ? { flow: stripItems(currentIoTraces.data, count, t), flow_note: flowNote(currentIoFlow.data, t) } : {}),
        } }).catch(error => console.error("Caption overlay could not be updated", error));
    }, [enabled, captions, flowShown, count, currentMessageLogs.data, currentOverlayShowOnlyTranslatedMessages.data,
        settings.position, settings.font_size, settings.opacity, settings.display_duration, currentSelectedFontFamily.data,
        currentIoTraces.data, currentIoFlow.data?.conversion_round_trip_ms, t]);

    return null;
};
