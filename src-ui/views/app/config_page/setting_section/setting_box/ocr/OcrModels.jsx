import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { useModelDownloads } from "../../../../../../logics/voice/useModelDownloads";
import voiceStyles from "../advanced_settings/VoiceSettings.module.scss";
import styles from "./Ocr.module.scss";
import { EnvReadout } from "../_components/env_readout/EnvReadout";

const activePhases = ["queued", "downloading", "verifying", "cancelling"];
const megabytes = value => `${(Number(value) / 1048576).toFixed(1)} MB`;

// Chat reading downloads (PP-OCR for the current language, or the optional chatbox
// detector). Same consent flow as the other default models: review source, terms,
// size and destination, then agree. Nothing needs applying afterwards: chat
// reading finds verified files by id.
export const OcrModels = ({ ids, missing, onChanged, title, desc, note }) => {
    const { t } = useI18n();
    const { catalog, state, error, pending, send } = useModelDownloads();
    const [selected, setSelected] = useState(null), [consent, setConsent] = useState(false);
    const [linkError, setLinkError] = useState(null);
    const dialog = useRef(null);
    const hasCatalog = !!catalog;

    useEffect(() => {
        if (!hasCatalog) send("/get/data/model_download_catalog");
        send("/get/data/model_download_state");
    }, [hasCatalog, send]);
    useEffect(() => { if (selected) dialog.current?.showModal(); }, [selected]);

    const entries = (catalog?.models ?? []).filter(entry => entry.target === "ocr" && ids.includes(entry.id));
    const readyIds = entries.filter(entry => state.jobs[entry.id]?.phase === "ready").map(entry => entry.id).join(",");
    useEffect(() => { if (readyIds) onChanged(); }, [readyIds, onChanged]);

    const busy = !!pending || Object.values(state.jobs).some(job => activePhases.includes(job.phase));
    const close = () => { setSelected(null); setConsent(false); setLinkError(null); };
    const failure = code => t(`model_downloads.errors.${code}`, { defaultValue: t("model_downloads.errors.download_failed") });
    const openLink = async (event, url) => {
        if (!isTauri()) return;
        event.preventDefault();
        try { await openUrl(url); setLinkError(null); }
        catch { setLinkError(url); }
    };

    return <section className={`${voiceStyles.container} ${styles.models}`} aria-label={title}>
        <h3>{title}</h3>
        {desc && <p>{desc}</p>}
        {!catalog && <p aria-busy="true">{t("model_downloads.loading")}</p>}
        {entries.map(entry => {
            const job = state.jobs[entry.id], active = activePhases.includes(job?.phase);
            const installed = !missing.includes(entry.id) || job?.phase === "ready";
            return <div key={entry.id} className={styles.modelRow}>
                <strong>{entry.name}</strong>
                <p>{entry.provider} · {megabytes(entry.total_bytes)} · {entry.license} · {note}</p>
                <EnvReadout tone={installed ? "active" : job?.phase === "failed" ? "failed" : "warning"}>
                    <p>{installed ? t("config_page.ocr.models.installed") : job ? t(`model_downloads.phase_${job.phase}`) : t("config_page.ocr.models.missing")}</p>
                </EnvReadout>
                {active && <><progress aria-label={t("model_downloads.progress")} value={job.received_bytes} max={job.total_bytes} />
                    <button type="button" disabled={!!pending || job.phase === "cancelling"}
                        onClick={() => send("/run/cancel_model_download", { id: entry.id, job_id: job.job_id })}>{t("model_downloads.cancel")}</button></>}
                {job?.error_code && <p role="alert">{failure(job.error_code)}</p>}
                {!installed && !active && <button type="button" className="primary" disabled={busy}
                    onClick={() => { setConsent(false); setSelected({ ...entry, catalog_version: catalog.catalog_version }); }}>
                    {t("model_downloads.review")}</button>}
            </div>;
        })}
        {selected && <dialog ref={dialog} aria-label={t("model_downloads.warning_title")} onCancel={close}>
            <h3>{t("model_downloads.warning_title")}</h3>
            <p>{selected.name} · {selected.provider}</p>
            <p>{Number(selected.total_bytes).toLocaleString("en-US")} bytes · {selected.license}</p>
            <p>{t(`model_downloads.notice_${selected.notice}`)}</p>
            <p>{t("model_downloads.connection_notice")}</p>
            <p>{t("model_downloads.source")}: {(selected.sources ?? [selected.source]).map(url =>
                <span key={url}> <a href={url} onClick={event => openLink(event, url)} target="_blank" rel="noreferrer">{url.replace("https://huggingface.co/", "").replace(/\/tree\/.*/, "")}</a> </span>)}</p>
            <p>{t("model_downloads.license_links")}: {selected.licenses.map((url, i) =>
                <span key={url}> <a href={url} onClick={event => openLink(event, url)} target="_blank" rel="noreferrer">{new URL(url).hostname === "www.apache.org" || url.endsWith("/LICENSE") ? selected.license : `${t("model_downloads.model_card")} (${i + 1})`}</a> </span>)}</p>
            {linkError && <div role="alert"><p>{t("model_downloads.link_error")}</p><code style={{ overflowWrap: "anywhere" }}>{linkError}</code></div>}
            <p>{t("model_downloads.destination")}: <code style={{ overflowWrap: "anywhere" }}>{selected.destination}</code></p>
            <ul>{selected.artifacts.map(file => <li key={file.filename}>{file.filename} · {Number(file.size).toLocaleString("en-US")} bytes</li>)}</ul>
            <label className={voiceStyles.checkLabel}><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />{t("model_downloads.consent")}</label>
            <div className={voiceStyles.actions}>
                <button type="button" autoFocus onClick={close}>{t("model_downloads.back")}</button>
                <button type="button" disabled={!consent || busy} onClick={() => {
                    send("/run/start_model_download", { id: selected.id, consent: true, catalog_version: selected.catalog_version }); close();
                }}>{t("model_downloads.start")}</button>
            </div>
        </dialog>}
        {error && <p role="alert">{failure(error)}</p>}
    </section>;
};
