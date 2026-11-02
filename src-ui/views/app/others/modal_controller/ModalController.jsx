import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import styles from "./ModalController.module.scss";
import { useStore_OpenedQuickSetting, useStore_IsOpenedDropdownMenu } from "@store";
import { Vr, Updater } from "@setting_box";

// A modal dialog for the quick settings. It closes with its button, Escape
// (unless a dropdown inside is open, which Escape closes first) or a click
// outside. Focus moves to the close button and back to the opener.
export const ModalController = () => {
    const { t } = useI18n();
    const { currentOpenedQuickSetting, updateOpenedQuickSetting } = useStore_OpenedQuickSetting();
    const { currentIsOpenedDropdownMenu } = useStore_IsOpenedDropdownMenu();
    const opened = currentOpenedQuickSetting.data;
    const closeButton = useRef(null);
    const dropdownOpen = useRef(false);
    dropdownOpen.current = currentIsOpenedDropdownMenu.data !== "";
    const close = () => updateOpenedQuickSetting("");

    useEffect(() => {
        if (opened === "") return;
        const opener = document.activeElement;
        closeButton.current?.focus({ preventScroll: true });
        const onKeyDown = event => {
            if (event.key === "Escape" && !dropdownOpen.current) close();
        };
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("keydown", onKeyDown);
            if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
        };
    }, [opened]);

    if (opened === "") return null;
    const title = opened === "overlay" ? t("config_page.vr.section_label_overlay") : t("config_page.side_menu_labels.updater");
    return (
        <div className={styles.container} role="dialog" aria-modal="true" aria-label={title}>
            <div className={styles.bg_onclick_close_area} onClick={close}></div>
            <div className={styles.wrapper}>
                <button type="button" ref={closeButton} className={styles.close_button} onClick={close}>
                    {t("common.close_button_label")}
                </button>
                <QuickSettingsController />
            </div>
        </div>
    );
};

const QuickSettingsController = () => {
    const { currentOpenedQuickSetting } = useStore_OpenedQuickSetting();

    switch (currentOpenedQuickSetting.data) {
        case "overlay":
            return <Vr />;
        case "update_software":
            return <Updater />;
        default:
            return null;
    }
};
