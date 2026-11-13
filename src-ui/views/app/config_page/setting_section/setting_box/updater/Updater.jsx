import { useI18n } from "@useI18n";
import { useSoftwareVersion } from "@logics_common";
import styles from "./Updater.module.scss";
import { SectionLabelComponent } from "../_components";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import { _OpenWebpageButton } from "../_components/_atoms/_open_webpage_button/_OpenWebpageButton";

// Fork updates are owned by the distribution channel. Keep the settings
// destination useful without offering an updater disabled by the backend.
// Laid out like the other pages: heading, the installed version as an
// environment readout, the policy, and the releases page as an external link.
export const Updater = () => {
    const { t } = useI18n();
    const { currentSoftwareVersion } = useSoftwareVersion();
    return (
        <div className={styles.container}>
            <SectionLabelComponent label={t("config_page.side_menu_labels.updater")} />
            <EnvReadout live={false}><p>VRCT-VOX {currentSoftwareVersion.data}</p></EnvReadout>
            <p className={styles.policy}>{t("fork_distribution.update_policy")}</p>
            <_OpenWebpageButton webpage_url="https://github.com/kein5/VRCT-VOX/releases" open_webpage_label={t("fork_distribution.releases")} />
        </div>
    );
};
