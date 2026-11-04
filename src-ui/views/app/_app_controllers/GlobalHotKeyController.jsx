import { useEffect } from "react";
import { useHotkeys } from "@logics_configs";
import { useIsBackendReady, useIsSoftwareUpdating, useIsOpenedConfigPage } from "@logics_common";

export const GlobalHotKeyController = () => {
    const { currentIsBackendReady } = useIsBackendReady();
    const { currentIsSoftwareUpdating } = useIsSoftwareUpdating();
    const { currentIsOpenedConfigPage } = useIsOpenedConfigPage();
    const { currentHotkeys, registerShortcuts, unregisterAll } = useHotkeys();
    // Pending saves retain the acknowledged data. Compare content so status-only
    // updates do not rebind, but a reply arriving after Settings closes does.
    const hotkeys = JSON.stringify(currentHotkeys.data);

    useEffect(() => {
        const is_backend_ready = currentIsBackendReady.data;
        const is_software_updating = currentIsSoftwareUpdating.data;

        if (is_backend_ready && !is_software_updating && !currentIsOpenedConfigPage.data) {
            registerShortcuts();
        } else {
            unregisterAll();
        }
        return () => { unregisterAll(); };
    }, [currentIsBackendReady.data, currentIsSoftwareUpdating.data, currentIsOpenedConfigPage.data, hotkeys]);

    return null;
};
