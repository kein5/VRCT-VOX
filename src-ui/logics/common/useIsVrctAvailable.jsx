import { useStore_IsVrctAvailable } from "@store";
import { useNotificationStatus } from "@logics_common";
import { TranslatedNotice } from "./TranslatedNotice";

export const useIsVrctAvailable = () => {
    const { currentIsVrctAvailable, updateIsVrctAvailable } = useStore_IsVrctAvailable();
    const { showNotification_Warning } = useNotificationStatus();

    const handleAiModelsAvailability = (is_ai_models_available) => {
        updateIsVrctAvailable(is_ai_models_available);
        if (is_ai_models_available === false) {
            showNotification_Warning(<TranslatedNotice k="runtime.local_models_unavailable" />, { hide_duration: 8000, category_id: "local_models_unavailable" });
        }
    };

    return {
        currentIsVrctAvailable,
        updateIsVrctAvailable,

        handleAiModelsAvailability,
    };
};
