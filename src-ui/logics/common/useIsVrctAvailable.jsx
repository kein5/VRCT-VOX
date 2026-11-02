import { useStore_IsVrctAvailable } from "@store";
import { useNotificationStatus } from "@logics_common";
import { useI18n } from "@useI18n";

// Translated when shown, not when created: this notice can arrive at startup
// before the saved UI language is applied.
const LocalModelsUnavailable = () => {
    const { t } = useI18n();
    return t("runtime.local_models_unavailable");
};

export const useIsVrctAvailable = () => {
    const { currentIsVrctAvailable, updateIsVrctAvailable } = useStore_IsVrctAvailable();
    const { showNotification_Warning } = useNotificationStatus();

    const handleAiModelsAvailability = (is_ai_models_available) => {
        updateIsVrctAvailable(is_ai_models_available);
        if (is_ai_models_available === false) {
            showNotification_Warning(<LocalModelsUnavailable />, { hide_duration: 8000, category_id: "local_models_unavailable" });
        }
    };

    return {
        currentIsVrctAvailable,
        updateIsVrctAvailable,

        handleAiModelsAvailability,
    };
};
