import { useStore_IsOscAvailable, useStore_OscUnavailableReason } from "@store";

// The reason a control that needs OSC reception is unavailable, as a locale key.
// With VRChat on another machine there is nothing to fix in the OSC settings.
export const oscUnavailableLabelKey = reason => reason === "remote_destination"
    ? "config_page.common.warning_labels.unable_to_use_osc_query_remote"
    : "config_page.common.warning_labels.unable_to_use_osc_query";

export const useIsOscAvailable = () => {
    const { currentIsOscAvailable, updateIsOscAvailable } = useStore_IsOscAvailable();
    const { currentOscUnavailableReason, updateOscUnavailableReason } = useStore_OscUnavailableReason();

    return {
        currentIsOscAvailable,
        updateIsOscAvailable,
        currentOscUnavailableReason,
        updateOscUnavailableReason,
        oscUnavailableLabelKey: oscUnavailableLabelKey(currentOscUnavailableReason.data),
    };
};
