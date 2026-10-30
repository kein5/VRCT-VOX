import { useStore_IsVrctAvailable } from "@store";
import { useNotificationStatus } from "@logics_common";
import { useI18n } from "@useI18n";

export const useIsVrctAvailable = () => {
    const { currentIsVrctAvailable, updateIsVrctAvailable } = useStore_IsVrctAvailable();
    const { showNotification_Warning } = useNotificationStatus();
    const { t } = useI18n();

    const handleAiModelsAvailability = (is_ai_models_available) => {
        updateIsVrctAvailable(is_ai_models_available);
        if (is_ai_models_available === false) {
            showNotification_Warning(t("runtime.local_models_unavailable"), { hide_duration: 8000 });
        }
    };

    return {
        currentIsVrctAvailable,
        updateIsVrctAvailable,

        handleAiModelsAvailability,
    };
};
