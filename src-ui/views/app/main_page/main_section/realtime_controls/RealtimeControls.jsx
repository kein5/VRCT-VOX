import { useI18n } from "@useI18n";
import { useIsOpenedConfigPage } from "@logics_common";
import { useRealtimeASR } from "../../../../../logics/transcription/useRealtimeASR";
import styles from "./RealtimeControls.module.scss";

export const RealtimeControls = () => {
    const { t } = useI18n();
    const { currentIsOpenedConfigPage } = useIsOpenedConfigPage();
    const { state, error, send } = useRealtimeASR();
    const active = ["mic", "speaker"].filter(source => state[source]?.requested);
    // Configuration has its own controls and pauses legacy translation. Keep
    // source Stop accessible from Main without entering that lifecycle.
    if (currentIsOpenedConfigPage.data || !active.length) return null;
    return <section className={styles.container} aria-label={t("realtime.title")}>
        {active.map(source => <div className={styles.source} key={source}>
            <p role="status">{t(`realtime.${source}`)}: {t(`realtime.state_${state[source].state}`)}</p>
            <button type="button" onClick={() => send("/run/stop_realtime_asr", { source })}>
                {t(`realtime.stop_${source}`)}
            </button>
        </div>)}
        {error && <p role="alert">{error}</p>}
    </section>;
};
