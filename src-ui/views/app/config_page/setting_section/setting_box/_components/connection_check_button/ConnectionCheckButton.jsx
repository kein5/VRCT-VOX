import styles from "./ConnectionCheckButton.module.scss";
import { useI18n } from "@useI18n";
import { EnvReadout } from "../env_readout/EnvReadout";

// The connection state is an environment readout in words (DESIGN.md); its
// color repeats the words. The check is the shared secondary settings button.
export const ConnectionCheckButton = (props) => {
    const { t } = useI18n();
    const pending = props.state === "pending";
    const state = pending ? "checking" : props.variable === true ? "connected" : "disconnected";

    return (
        <EnvReadout
            className={styles.container}
            tone={state === "connected" ? "active" : "neutral"}
            actions={
                <button type="button" className={styles.button} disabled={pending} onClick={props.checkFunction}>
                    {t("config_page.common.connection_check.button_label")}
                </button>
            }
        >
            <p>{t(`config_page.common.connection_check.${state}`)}</p>
        </EnvReadout>
    );
};
