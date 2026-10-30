import { useStore_IsMainPageCompactMode, useStore_IsBreakPoint } from "@store";
import { useStdoutToPython } from "@useStdoutToPython";

export const useIsMainPageCompactMode = () => {
    const { currentIsBreakPoint } = useStore_IsBreakPoint();
    const isAutomaticCompact = currentIsBreakPoint.data;
    const { asyncStdoutToPython } = useStdoutToPython();
    const { currentIsMainPageCompactMode, updateIsMainPageCompactMode } = useStore_IsMainPageCompactMode();

    const getIsMainPageCompactMode = () => {
        asyncStdoutToPython("/get/data/main_window_sidebar_compact_mode");
    };

    const toggleIsMainPageCompactMode = () => {
        if (isAutomaticCompact) return;
        if (currentIsMainPageCompactMode.data) {
            asyncStdoutToPython("/set/disable/main_window_sidebar_compact_mode");
        } else {
            asyncStdoutToPython("/set/enable/main_window_sidebar_compact_mode");
        }
    };

    return {
        currentIsMainPageCompactMode: { ...currentIsMainPageCompactMode, data: currentIsMainPageCompactMode.data || isAutomaticCompact },
        isAutomaticCompact,
        getIsMainPageCompactMode,
        toggleIsMainPageCompactMode,
        updateIsMainPageCompactMode,
    };
};