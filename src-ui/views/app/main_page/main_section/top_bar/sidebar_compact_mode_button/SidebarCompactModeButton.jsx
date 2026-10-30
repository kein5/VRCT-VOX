import { useI18n } from "@useI18n";
import clsx from "clsx";
import styles from "./SidebarCompactModeButton.module.scss";

import { useIsMainPageCompactMode } from "@logics_main";
import ArrowLeftSvg from "@images/arrow_left.svg?react";

export const SidebarCompactModeButton = () => {
    const { t } = useI18n();
    const { toggleIsMainPageCompactMode, currentIsMainPageCompactMode, isAutomaticCompact } = useIsMainPageCompactMode();

    const class_names = clsx(styles["arrow_left_svg"], {
        [styles["reverse"]]: currentIsMainPageCompactMode.data
    });

    return (
        <button type="button" disabled={isAutomaticCompact} aria-label={t("studio.toggle_sidebar")} className={styles.container} onClick={toggleIsMainPageCompactMode}>
            <ArrowLeftSvg className={class_names} preserveAspectRatio="none" />
        </button>
    );
};