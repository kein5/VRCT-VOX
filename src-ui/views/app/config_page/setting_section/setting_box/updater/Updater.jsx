import { useI18n } from "@useI18n";
import { useSoftwareVersion } from "@logics_common";
import styles from "./Updater.module.scss";

// Fork updates are owned by the distribution channel. Keep the settings
// destination useful without offering an updater disabled by the backend.
export const Updater = () => {
    const { t } = useI18n();
    const { currentSoftwareVersion } = useSoftwareVersion();
    return (
        <div className={styles.container}>
            <p>VRCT-TTS {currentSoftwareVersion.data}</p>
            <p>{t("fork_distribution.update_policy")}</p>
            <a href="https://github.com/kein5/VRCT-TTS/releases" target="_blank" rel="noreferrer">
                {t("fork_distribution.releases")}
            </a>
        </div>
    );
};
