import { useI18n } from "@useI18n";
import styles from "./Topbar.module.scss";
import { useIsOpenedConfigPage } from "@logics_common";
import ArrowLeftSvg from "@images/arrow_left.svg?react";

export const Topbar = () => {
    const { t } = useI18n();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();
    return <div className={styles.container}>
        <button type="button" className={styles.back} onClick={() => setIsOpenedConfigPage(false)}>
            <ArrowLeftSvg aria-hidden="true" />
            {t("common.go_back_button_label")}
        </button>
    </div>;
};
