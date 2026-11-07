import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { activeSetupPhases, useVcRuntimes } from "../../../../../../logics/voice/useVcRuntimes";
import { useConsentDialog } from "../../../../../../logics/common/useConsentDialog";
import styles from "./VoiceSettings.module.scss";
import { EnvReadout } from "../_components/env_readout/EnvReadout";

const gb = value => `${(value / 1e9).toFixed(1)} GB`;

// Offers to prepare an engine's runtime where the backend can; elsewhere it renders nothing.
export const VcRuntimeSetup = ({ engine, current, disabled, onUse }) => {
    const { t } = useI18n();
    const { catalog, state, error, pending, send } = useVcRuntimes();
    const [open, setOpen] = useState(false), [consent, setConsent] = useState(false), [linkError, setLinkError] = useState(null);
    const section = useRef(null);
    const { dialog, close: closeDialog } = useConsentDialog(open, section);
    useEffect(() => {
        send("/get/data/vc_runtime_catalog"); send("/get/data/vc_runtime_state");
    }, [send]);
    const entry = catalog?.runtimes?.find(row => row.id === engine);
    if (!entry) return null;
    const job = state.jobs[engine], installed = state.installed[engine];
    const active = activeSetupPhases.includes(job?.phase);
    const busy = !!pending || Object.values(state.jobs).some(item => activeSetupPhases.includes(item.phase));
    const failure = code => t(`vc_runtime.errors.${code}`, { defaultValue: t("vc_runtime.errors.vc_runtime_failed") });
    const close = () => { closeDialog(); setOpen(false); setConsent(false); setLinkError(null); };
    const openLink = async (event, url) => {
        if (!isTauri()) return;
        event.preventDefault();
        try { await openUrl(url); setLinkError(null); }
        catch { setLinkError(url); }
    };
    return <section ref={section} tabIndex={-1} className={styles.download_entry} aria-label={t("vc_runtime.title", { name: entry.name })}>
        <strong>{t("vc_runtime.title", { name: entry.name })}</strong>
        <p>{t("vc_runtime.help")}</p>
        {!installed && <p>{t("vc_runtime.size", { download: gb(entry.download_bytes), disk: gb(entry.disk_bytes) })} · {entry.license}</p>}
        {!entry.gpu_ready && !installed && <p role="alert">{t("vc_runtime.gpu_missing")}</p>}
        {job && <EnvReadout tone={job.phase === "ready" ? "active" : job.phase === "failed" ? "failed" : "neutral"}>
            <p>{t(`vc_runtime.phase_${job.phase}`)}{active && job.step > 0 && ` · ${job.step} / ${job.steps}`}</p>
        </EnvReadout>}
        {active && <progress className={styles.progress} aria-label={t("vc_runtime.progress")}
            value={job.total_bytes ? job.received_bytes : job.step} max={job.total_bytes || job.steps} />}
        {job?.error_code && <p role="alert">{failure(job.error_code)}</p>}
        {error && <p role="alert">{failure(error)}</p>}
        {installed && <p>{t("vc_runtime.installed")}: <code style={{ overflowWrap: "anywhere" }}>{installed}</code></p>}
        <div className={styles.actions}>
            {active && <button type="button" disabled={job.phase === "cancelling" || !!pending}
                onClick={() => send("/run/cancel_vc_runtime_setup", { id: engine, job_id: job.job_id })}>{t("vc_runtime.cancel")}</button>}
            {installed && installed !== current && <button type="button" disabled={disabled} onClick={() => onUse(installed)}>{t("vc_runtime.use")}</button>}
            {!installed && !active && <button type="button" disabled={busy || !entry.gpu_ready}
                onClick={() => { setConsent(false); setOpen(true); }}>{t(job ? "vc_runtime.resume" : "vc_runtime.review")}</button>}
        </div>
        {open && <dialog ref={dialog} aria-label={t("vc_runtime.warning_title")} onCancel={event => { event.preventDefault(); close(); }}>
            <h3>{t("vc_runtime.warning_title")}</h3>
            <p>{t(`vc_runtime.notice_${entry.notice}`)}</p>
            <p>{t("vc_runtime.size", { download: gb(entry.download_bytes), disk: gb(entry.disk_bytes) })}</p>
            <p>{t("vc_runtime.connection_notice")}</p>
            <p>{t("vc_runtime.no_start")}</p>
            <p>{t("model_downloads.license_links")}: {entry.licenses.map(url => <span key={url}> <a href={url} onClick={event => openLink(event, url)} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>{url}</a> </span>)}</p>
            {linkError && <div role="alert"><p>{t("model_downloads.link_error")}</p><code style={{ overflowWrap: "anywhere" }}>{linkError}</code></div>}
            <p>{t("model_downloads.destination")}: <code style={{ overflowWrap: "anywhere" }}>{entry.destination}</code></p>
            <label className={styles.checkLabel}><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />{t("vc_runtime.consent")}</label>
            <div className={styles.actions}>
                <button type="button" autoFocus onClick={close}>{t("model_downloads.back")}</button>
                <button type="button" disabled={!consent || busy} onClick={() => {
                    if (!consent || busy) return;
                    send("/run/start_vc_runtime_setup", { id: engine, consent: true, version: entry.version }); close();
                }}>{t("vc_runtime.start")}</button>
            </div>
        </dialog>}
    </section>;
};
