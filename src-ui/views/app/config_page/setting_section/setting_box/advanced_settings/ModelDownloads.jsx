import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { useModelDownloads } from "../../../../../../logics/voice/useModelDownloads";
import { modelAdvice } from "../../../../../../logics/voice/modelHardwareAdvice";
import styles from "./VoiceSettings.module.scss";

const activePhases = ["queued", "downloading", "verifying", "cancelling"];
const bytes = value => `${Number(value).toLocaleString("en-US")} bytes (${(value / 1073741824).toFixed(2)} GiB)`;

export const ModelDownloads = ({ targets, expected, blocked = false, deviceMode = 'auto' }) => {
    const { t } = useI18n();
    const { catalog, state, hardware, error, pending, send, ensureHardware } = useModelDownloads();
    const [selected, setSelected] = useState(null), [consent, setConsent] = useState(false);
    const [linkError, setLinkError] = useState(null);
    const [choices, setChoices] = useState({}), [reserve, setReserve] = useState('vr');
    const [, setNow] = useState(Date.now());
    const ttsTargets = targets.filter(target => ['japanese', 'multilingual'].includes(target));
    const hasTTS = ttsTargets.length > 0;
    const dialog = useRef(null);
    useEffect(() => {
        send("/get/data/model_download_catalog"); send("/get/data/model_download_state");
    }, [send]);
    useEffect(() => { if (hasTTS) ensureHardware(); }, [hasTTS, hardware.phase, ensureHardware]);
    useEffect(() => {
        if (!hasTTS) return;
        const timer = setInterval(() => setNow(Date.now()), 5000);
        return () => clearInterval(timer);
    }, [hasTTS]);
    useEffect(() => { if (selected) dialog.current?.showModal(); }, [selected]);
    const busy = !!pending || Object.values(state.jobs).some(job => activePhases.includes(job.phase));
    const close = () => { setSelected(null); setConsent(false); setLinkError(null); };
    const openLink = async (event, url) => {
        if (!isTauri()) return;
        event.preventDefault();
        try { await openUrl(url); setLinkError(null); }
        catch { setLinkError(url); }
    };
    const request = (endpoint, entry, job) => send(endpoint, { id: entry.id, job_id: job.job_id });
    const failure = code => t(`model_downloads.errors.${code}`, { defaultValue: t("model_downloads.errors.download_failed") });
    const matching = catalog?.models.filter(entry => targets.includes(entry.target)) ?? [];
    const advice = Object.fromEntries(targets.map(target => [target, modelAdvice(matching.filter(entry => entry.target === target),
        hardware, { now: Date.now(), deviceMode, reserveBytes: (reserve === 'vr' ? 2 : .5) * 1024 ** 3 })]));
    const choice = target => matching.find(entry => entry.target === target && entry.id === choices[target])?.id
        ?? advice[target].recommended ?? matching.find(entry => entry.target === target)?.id;
    const memory = value => Number.isFinite(value) ? `${(value / 1024 ** 3).toFixed(2)} GiB` : t('model_downloads.hardware_unknown');
    return <section className={styles.container} aria-label={t("model_downloads.title")}>
        <h4>{t("model_downloads.title")}</h4>
        <p>{t("model_downloads.help")}</p>
        {!catalog && <p aria-busy="true">{t("model_downloads.loading")}</p>}
        {hasTTS && <>
            <label>{t('model_downloads.headroom')}<select aria-label={t('model_downloads.headroom')} value={reserve} onChange={event => setReserve(event.target.value)}>
                <option value="vr">{t('model_downloads.headroom_vr')}</option>
                <option value="alone">{t('model_downloads.headroom_alone')}</option>
            </select></label>
            <button type="button" disabled={hardware.phase === 'probing'} onClick={() => send('/run/refresh_model_download_hardware', {})}>
                {t('model_downloads.hardware_refresh')}</button>
            {hardware.phase === 'probing' && <p aria-busy="true">{t('model_downloads.hardware_probing')}</p>}
            {ttsTargets.map(target => {
                const hint = advice[target], rows = matching.filter(entry => entry.target === target);
                return <div key={target}>
                    {hint.device && <p>{hint.device.name}: {hint.device.description} · {t('model_downloads.hardware_free')}: {memory(hint.device.memory_free)} / {t('model_downloads.hardware_total')}: {memory(hint.device.memory_total)}</p>}
                    {hardware.measured_at_ms && <p>{t('model_downloads.hardware_measured')}: {new Date(hardware.measured_at_ms).toLocaleTimeString()}</p>}
                    <p>{t(`model_downloads.advice_${hint.reason}`)}</p>
                    {hint.multiple && <p>{t('model_downloads.multiple_gpus')}</p>}
                    {rows.length > 0 && <label>{t('model_downloads.variant')}<select aria-label={t('model_downloads.variant')} value={choice(target)}
                        onChange={event => setChoices(previous => ({ ...previous, [target]: event.target.value }))}>
                        {rows.map(entry => <option key={entry.id} value={entry.id}>{entry.name} · {memory(entry.total_bytes)}</option>)}
                    </select></label>}
                    {hint.recommended && <p><strong>{t('model_downloads.recommended')}</strong>: {rows.find(entry => entry.id === hint.recommended)?.name}</p>}
                    {hint.recommended && choice(target) !== hint.recommended && <p>{t('model_downloads.manual_choice')}</p>}
                </div>;
            })}
            <p>{t('model_downloads.memory_boundary')}</p>
        </>}
        {matching.filter(entry => entry.id === choice(entry.target) || activePhases.includes(state.jobs[entry.id]?.phase) || state.jobs[entry.id]?.phase === 'ready').map(entry => {
            const job = state.jobs[entry.id], active = activePhases.includes(job?.phase);
            return <div key={entry.id}>
                <strong>{entry.name}</strong>
                <p>{entry.provider} · {bytes(entry.total_bytes)} · {entry.license}</p>
                {entry.guidance?.reference_memory_bytes && <>
                    <p>{t(`model_downloads.tier_${entry.guidance.tier}`)} · {t('model_downloads.memory_reference')}: {memory(entry.guidance.reference_memory_bytes)}</p>
                    <p>{t(`model_downloads.validation_${entry.guidance.validation.state}`)} {entry.guidance.validation.device ?? ''}</p>
                    {entry.guidance.validation.scope && <p>{t(`model_downloads.scope_${entry.guidance.validation.scope}`)}</p>}
                    {advice[entry.target].device && advice[entry.target].device.description !== entry.guidance.validation.device && <p>{t('model_downloads.gpu_unverified')}</p>}
                </>}
                {entry.target === "rvc" && <p>{t("model_downloads.rvc_requirements")}</p>}
                {entry.target === "asr" && <p>{t("model_downloads.asr_requirements")}</p>}
                {job && <p role="status">{t(`model_downloads.phase_${job.phase}`)}</p>}
                {active && <><progress aria-label={t("model_downloads.progress")} value={job.received_bytes} max={job.total_bytes} />
                    <p>{bytes(job.received_bytes)} / {bytes(job.total_bytes)}</p>
                    <button type="button" disabled={!!pending || job.phase === "cancelling"}
                        onClick={() => request("/run/cancel_model_download", entry, job)}>{t("model_downloads.cancel")}</button></>}
                {job?.error_code && <p role="alert">{failure(job.error_code)}</p>}
                <button type="button" disabled={busy} onClick={() => { setConsent(false); setSelected({ ...entry, catalog_version: catalog.catalog_version }); }}>{t("model_downloads.review")}</button>
                {job?.phase === "ready" && <>
                    <p>{t("model_downloads.apply_hint")}</p>
                    <button type="button" disabled={busy || blocked || !expected?.[entry.target]}
                        onClick={() => send("/run/apply_model_download", { id: entry.id, job_id: job.job_id, expected: expected[entry.target] })}>{t("model_downloads.apply")}</button>
                    {blocked && <p>{t("model_downloads.blocked")}</p>}
                </>}
            </div>;
        })}
        {selected && <dialog ref={dialog} aria-label={t("model_downloads.warning_title")} onCancel={close}>
            <h3>{t("model_downloads.warning_title")}</h3>
            <p>{selected.name} · {selected.provider}</p>
            <p>{bytes(selected.total_bytes)} · {selected.license}</p>
            <p>{t(`model_downloads.notice_${selected.notice}`)}</p>
            {selected.target === "rvc" && <p>{t("model_downloads.rvc_requirements")}</p>}
            {selected.target === "asr" && <p>{t("model_downloads.asr_requirements")}</p>}
            <p>{t("model_downloads.connection_notice")}</p>
            <p>{t("model_downloads.no_start")}</p>
            <p>{t("model_downloads.source")}: <a href={selected.source} onClick={event => openLink(event, selected.source)} target="_blank" rel="noreferrer">{selected.repo}</a></p>
            <p>{t("model_downloads.license_links")}: {selected.licenses.map((url, i) => <span key={url}> <a href={url} onClick={event => openLink(event, url)} target="_blank" rel="noreferrer">{i === 0 ? t("model_downloads.model_card") : `${selected.license} (${i})`}</a> </span>)}</p>
            {linkError && <div role="alert"><p>{t("model_downloads.link_error")}</p><code style={{ overflowWrap: "anywhere" }}>{linkError}</code></div>}
            <p>{t("model_downloads.destination")}: <code style={{ overflowWrap: "anywhere" }}>{selected.destination}</code></p>
            <ul>{selected.artifacts.map(file => <li key={file.filename}>{file.filename} · {bytes(file.size)}</li>)}</ul>
            <label className={styles.checkLabel}><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />{t("model_downloads.consent")}</label>
            <div className={styles.actions}>
                <button type="button" autoFocus onClick={close}>{t("model_downloads.back")}</button>
                <button type="button" disabled={!consent || busy} onClick={() => {
                    send("/run/start_model_download", { id: selected.id, consent: true, catalog_version: selected.catalog_version }); close();
                }}>{t("model_downloads.start")}</button>
            </div>
        </dialog>}
        {error && <p role="alert">{failure(error)}</p>}
        {!catalog && <button type="button" onClick={() => send("/get/data/model_download_catalog")}>{t("voice.retry")}</button>}
    </section>;
};
