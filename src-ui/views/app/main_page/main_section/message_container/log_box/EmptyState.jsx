import { useI18n } from "@useI18n";
import { store } from "@store";
import { useSettingValue } from "@logics_configs";
import { useSetupNeeds } from "../../../../../../logics/main/useSetupNeeds";
import { downloadProgress } from "../../../../../../logics/main/setupNeeds";
import styles from "./LogBox.module.scss";

// The first screen of a session. It says where to type and, in the main window,
// what the selected engines still need, each with the step that provides it.
export const EmptyState = () => {
    const { t } = useI18n();
    return <div className={styles.empty}>
        <h1>{t("studio.empty_title")}</h1>
        <p>{t("studio.empty_description")}</p>
        {!store.is_vr_panel && <Setup />}
    </div>;
};

const Setup = () => {
    const { t } = useI18n();
    const { needs, start } = useSetupNeeds();
    const sends = useSettingValue("EnableSendMessageToVrc");
    return <>
        {needs.length > 0 && <ul className={styles.setup} aria-label={t("studio.setup_label")}>
            {needs.map(({ id, weight }) => {
                const progress = downloadProgress(weight);
                return <li key={id}>
                    <span>{t(`studio.setup_${id}`)}</span>
                    {progress === null
                        ? <button type="button" onClick={() => start(id)}>{t("model_downloads.review")}</button>
                        : <span role="status">{t(progress === "pending" ? "studio.setup_preparing" : "studio.setup_downloading", { progress })}</span>}
                </li>;
            })}
        </ul>}
        {sends?.data === true && <p className={styles.hint}>{t("studio.empty_vrchat_hint")}</p>}
    </>;
};
