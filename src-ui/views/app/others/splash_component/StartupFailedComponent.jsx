import { useI18n } from "@useI18n";
import { useWindow } from "@logics_common";
import { useBackendStartup } from "../../../../logics/common/useBackendStartup";
import { CloseButton } from "@common_components";
import styles from "./SplashComponent.module.scss";

export const StartupFailedComponent = () => {
    const { t } = useI18n();
    const { retryStartup } = useBackendStartup();
    const { asyncCloseApp } = useWindow();
    return (
        <div className={styles.failed_container}>
            <div className={styles.failed_scroll}>
                <div className={styles.failed_notice} role="alert">
                    <p>{t("common_error.backend_startup_failed")}</p>
                    <button type="button" className={styles.retry_button} onClick={retryStartup}>
                        {t("common_error.backend_startup_retry")}
                    </button>
                </div>
            </div>
            <CloseButton aria-label={t("studio.close")} onClick={asyncCloseApp} />
        </div>
    );
};
