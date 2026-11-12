import { useStore_IsVrctAvailable } from "@store";

// Whether the built-in models the selected engines need are there. The engine
// reports it at startup. What is missing is shown in the empty conversation,
// with a way to fetch it (logics/main/useSetupNeeds.js), instead of a notice.
export const useIsVrctAvailable = () => {
    const { currentIsVrctAvailable, updateIsVrctAvailable } = useStore_IsVrctAvailable();

    const handleAiModelsAvailability = (is_ai_models_available) => {
        updateIsVrctAvailable(is_ai_models_available);
    };

    return {
        currentIsVrctAvailable,
        updateIsVrctAvailable,

        handleAiModelsAvailability,
    };
};
