import { useI18n } from "@useI18n";
import { useOthers } from "@logics_configs";
import { telemetryRows, sentSummary } from "../../../../../../../logics/common/telemetryRows";
import styles from "./TelemetryContents.module.scss";

// "See what is sent": the usage event this PC would send now, field by field and as the
// data itself, and (with_sent) what was sent before. The backend builds it with the call
// that builds what it sends. It is asked for when the user opens it, not before.
export const TelemetryContents = ({ with_sent = false }) => {
    const { t } = useI18n();
    const { currentTelemetryPreview, getTelemetryPreview } = useOthers();
    const preview = currentTelemetryPreview.data;
    const event = preview?.app_started;

    return <details className={styles.contents} onToggle={toggled => { if (toggled.currentTarget.open) getTelemetryPreview(); }}>
        <summary>{t("telemetry_contents.show")}</summary>
        {!event
            ? <p role="status">{t(currentTelemetryPreview.state === "pending" || preview == null
                ? "telemetry_contents.loading" : "telemetry_contents.unavailable")}</p>
            : <>
                <p>{t("telemetry_contents.intro")}</p>
                <dl className={styles.rows}>
                    {telemetryRows(event, t).map(row => <div key={row.key} className={styles.row}>
                        <dt>{row.label}</dt><dd>{row.value}</dd>
                    </div>)}
                </dl>
                <p>{t("telemetry_contents.error_note")}</p>
                {preview.endpoint && <p>{t("telemetry_contents.destination", { endpoint: preview.endpoint })}</p>}
                <details className={styles.raw}>
                    <summary>{t("telemetry_contents.raw")}</summary>
                    <pre tabIndex={0}>{JSON.stringify(event, null, 2)}</pre>
                </details>
                {with_sent && <section className={styles.sent} aria-label={t("telemetry_contents.sent_title")}>
                    <h4>{t("telemetry_contents.sent_title")}</h4>
                    {(preview.sent ?? []).length === 0
                        ? <p>{t("telemetry_contents.sent_none")}</p>
                        : <ul>
                            {[...preview.sent].reverse().map((row, index) => <li key={`${row.at}-${index}`}>
                                <details className={styles.raw}>
                                    <summary>{row.at} — {sentSummary(row.body, t)} — {t(row.accepted ? "telemetry_contents.sent_accepted" : "telemetry_contents.sent_failed")}</summary>
                                    <pre tabIndex={0}>{JSON.stringify(row.body, null, 2)}</pre>
                                </details>
                            </li>)}
                        </ul>}
                </section>}
            </>}
    </details>;
};
