import { useI18n } from "@useI18n";
import { useIoFlow } from "../../../../../logics/flow/useIoFlow";
import { IoFlowView } from "../../../io_flow/IoFlowView";
import styles from "./IoFlowPanel.module.scss";

// Opened from the top bar: where the user's voice and chat go now, and how long the latest
// of each took. It sits above the conversation and scrolls on its own, so the log and the
// composer stay usable while it is open.
export const IoFlowPanel = () => {
    const { t } = useI18n();
    const { isPanelOpen, togglePanel, currentIoFlow, currentIoTraces } = useIoFlow();
    if (!isPanelOpen) return null;
    return <section id="io_flow_panel" className={styles.panel} aria-label={t("io_flow.title")}>
        <div className={styles.head}>
            <h2 className={styles.title}>{t("io_flow.title")}</h2>
            <p className={styles.hint}>{t("io_flow.hint")}</p>
            <button type="button" className={styles.close} onClick={togglePanel}>{t("io_flow.close")}</button>
        </div>
        <IoFlowView flow={currentIoFlow.data} traces={currentIoTraces.data} />
    </section>;
};
