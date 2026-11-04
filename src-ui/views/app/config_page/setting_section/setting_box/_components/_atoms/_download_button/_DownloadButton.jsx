import { useI18n } from "@useI18n";
import { CircularProgress } from "@common_components";
import styles from "./_DownloadButton.module.scss";
import { legacyDownloadPhase, useLegacyDownloadStatus } from "../../../../../../../../logics/common/useLegacyDownloadStatus";

export const _DownloadButton = ({option, ...props}) => {
    const { t } = useI18n();
    const model = `${props.name === "ctranslate2_weight_type" ? "CTranslate2" : "Whisper"} ${option.label ?? option.id}`;
    const progressName = t("legacy_model_downloads.progress_name", { model });
    const status = useLegacyDownloadStatus(option, model, t);
    const phase = legacyDownloadPhase(option);

    const renderContent = () => {
        switch (true) {
            case Number.isFinite(option.progress):
                return (
                    <div className={styles.progress_wrapper}>
                        <CircularProgress
                            aria-label={progressName}
                            variant={phase === "finalizing" ? "indeterminate" : "determinate"}
                            value={option.progress}
                            size="3rem"
                            sx={{ color: "var(--primary_300_color)" }}
                        />
                        <p className={styles.progress_label} aria-hidden="true">{`${Math.round(option.progress)}%`}</p>
                    </div>
                );
            case option.is_pending:
                return (
                    <div className={styles.progress_wrapper}>
                        <CircularProgress aria-label={progressName} size="3rem" sx={{ color: "var(--dark_600_color)" }}/>
                    </div>
                );
            case !option.is_downloaded:
                return (
                    <button
                        className={styles.download_button}
                        onClick={() => props.downloadStartFunction(option.id)}
                    >
                        <p className={styles.download_button_label}>{t("config_page.common.model_download_button_label")}</p>
                    </button>
                );
            case option.is_default:
                return (
                    <span className={styles.default_badge}>
                        {t("common.default_label")}
                    </span>
                );
            case option.update_button:
                return (
                    <button
                        className={styles.update_button}
                        onClick={() => props.downloadStartFunction(option.id)}
                    >
                        <p className={styles.download_button_label}>Update</p>
                    </button>
                );
            default:
                return null;
        }
    };

    return <div className={styles.download_container}>
        {renderContent()}
        <span className={styles.status} role="status" aria-live="polite" aria-atomic="true">{status}</span>
    </div>;
};
