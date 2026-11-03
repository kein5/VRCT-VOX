import { store, useStore_BackendStartupState } from "@store";

export const useBackendStartup = () => {
    const { currentBackendStartupState } = useStore_BackendStartupState();
    return {
        startupState: currentBackendStartupState.data,
        retryStartup: () => store.backend_session_owner?.retry(),
    };
};
