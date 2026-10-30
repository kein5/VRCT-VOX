import { useI18n } from "@useI18n";
import styles from "./OpenSettings.module.scss";
import { useIsOpenedConfigPage } from "@logics_common";
import ConfigurationSvg from "@images/configuration.svg?react";

export const OpenSettings = () => {
    const { t } = useI18n();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();

    const openConfigPage = () => {
        setIsOpenedConfigPage(true);
    };

    return (
        <div className={styles.container}>
            <button data-open-settings type="button" aria-label={t("studio.open_settings")} title={t("studio.open_settings")} className={styles.open_config_page_button} onClick={openConfigPage}>
                <ConfigurationSvg aria-hidden="true" className={styles.configuration_svg} />
            </button>
        </div>
    );
};