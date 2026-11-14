import { useEffect } from "react";
import { store } from "@store";
import { useStdoutToPython } from "@useStdoutToPython";
import { useIsBackendReady } from "@logics_common";
import { useVr } from "@logics_configs";
import { useIoFlow } from "../../../logics/flow/useIoFlow";

// The route map follows the settings, so it is read again every second while something
// shows it: the panel in this window, the desktop strip, or the VR window (which mirrors it).
// Stage times need no polling; the backend pushes them as messages go out.
export const IoFlowController = () => {
    const { asyncStdoutToPython } = useStdoutToPython();
    const { currentIsBackendReady } = useIsBackendReady();
    const { currentIsEnabledOverlayVrPanel, currentIoFlowOverlaySettings } = useVr();
    const { isPanelOpen } = useIoFlow();
    const shown = isPanelOpen || currentIoFlowOverlaySettings.data?.desktop === true
        || currentIsEnabledOverlayVrPanel.data === true;
    const ready = currentIsBackendReady.data === true;

    useEffect(() => {
        if (!ready || !shown) return undefined;
        const read = () => { if (!store.backend_stopped) asyncStdoutToPython("/get/data/io_flow"); };
        read();
        const timer = setInterval(read, 1000);
        return () => clearInterval(timer);
    }, [ready, shown]);

    return null;
};
