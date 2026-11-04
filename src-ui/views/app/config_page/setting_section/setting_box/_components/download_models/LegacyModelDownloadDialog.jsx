import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { useModelDownloads } from "../../../../../../../logics/voice/useModelDownloads";
import { legacyDownloadRequest, legacyReviewSize } from "../../../../../../../logics/configs/legacyModelConsent";
import styles from "../../advanced_settings/VoiceSettings.module.scss";
import dialogStyles from "./LegacyModelDownloadDialog.module.scss";
import { useConsentDialog } from "../../../../../../../logics/common/useConsentDialog";

// Native modal scope, initial focus on Back and the shared catalog form styles.
// A snapshot remains on screen until closed, even if the catalog is refreshed.
export const LegacyModelDownloadDialog = ({ kind, weightType, onCancel, onDownload }) => {
    const { t } = useI18n();
    const { catalog, error, send } = useModelDownloads();
    const [entry, setEntry] = useState(null), [consent, setConsent] = useState(false);
    const [linkError, setLinkError] = useState(null);
    const { dialog, close } = useConsentDialog(true);
    const submitted = useRef(false);
    const cancel = () => { close(); onCancel(); };
    useEffect(() => {
        send("/get/data/model_download_catalog");
    }, [send]);
    useEffect(() => {
        const reviewed = catalog?.legacy_models?.find(item => item.kind === kind && item.weight_type === weightType);
        if (reviewed) setEntry(previous => previous ?? reviewed);
    }, [catalog, kind, weightType]);
    const openLink = async (event, url) => {
        if (!isTauri()) return;
        event.preventDefault();
        try { await openUrl(url); setLinkError(null); }
        catch { setLinkError(url); }
    };
    const modelCard = model => `https://huggingface.co/${model.repo}/blob/${model.revision}/README.md`;
    const revision = value => <code title={value} aria-description={value}>{value.slice(0, 12)}</code>;
    const request = legacyDownloadRequest(entry, consent);
    return <div className={`${styles.container} ${dialogStyles.host}`}>
        <dialog ref={dialog} className={dialogStyles.dialog} aria-label={t("model_downloads.warning_title")} onCancel={event => { event.preventDefault(); cancel(); }}>
            <h3>{t("model_downloads.warning_title")}</h3>
            {entry ? <>
                <dl className={dialogStyles.facts}>
                    <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.model")}</dt><dd>{entry.name}</dd>
                    </div>
                    <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.provider")}</dt><dd>{entry.provider}</dd>
                    </div>
                    <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.license")}</dt>
                        <dd>{entry.license}
                            {entry.non_commercial && <p role="alert">{t("legacy_model_downloads.non_commercial")}</p>}
                        </dd>
                    </div>
                    <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.size")}</dt><dd>{legacyReviewSize(entry, t)}</dd>
                    </div>
                    {entry.tokenizer && <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.additional_files")}</dt>
                        <dd>{t("legacy_model_downloads.tokenizer_label")}: <a href={modelCard(entry.tokenizer)}
                            onClick={event => openLink(event, modelCard(entry.tokenizer))} target="_blank" rel="noreferrer">{entry.tokenizer.repo}</a>
                            {" ("}{t("legacy_model_downloads.revision_label")} {revision(entry.tokenizer.revision)}{")"}
                            {entry.tokenizer.bundled && <p>{t("legacy_model_downloads.included_tokenizer")}</p>}
                            {entry.tokenizer_size_unknown && <p>{t("legacy_model_downloads.plus_tokenizer")}</p>}
                        </dd>
                    </div>}
                    <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.revision_label")}</dt><dd>{revision(entry.revision)}</dd>
                    </div>
                    <div className={dialogStyles.fact}>
                        <dt>{t("legacy_model_downloads.terms")}</dt>
                        <dd><a href={modelCard(entry)} onClick={event => openLink(event, modelCard(entry))}
                            target="_blank" rel="noreferrer">{t("model_downloads.model_card")} ({entry.repo})</a></dd>
                    </div>
                </dl>
                {linkError && <div role="alert"><p>{t("model_downloads.link_error")}</p><code>{linkError}</code></div>}
                <p>{t("legacy_model_downloads.no_start")}</p>
                <label className={styles.checkLabel}><input type="checkbox" checked={consent}
                    onChange={event => setConsent(event.target.checked)} />{t(entry.tokenizer
                        ? "legacy_model_downloads.consent" : "legacy_model_downloads.consent_without_extra_files")}</label>
            </> : <p role="status">{t(error ? "legacy_model_downloads.review_unavailable" : "model_downloads.loading")}</p>}
            <div className={styles.actions}>
                <button type="button" autoFocus onClick={cancel}>{t("model_downloads.back")}</button>
                <button type="button" disabled={!request} onClick={() => {
                    if (!request || submitted.current) return;
                    submitted.current = true;
                    close(); onDownload(request); onCancel();
                }}>{t("model_downloads.start")}</button>
            </div>
        </dialog>
    </div>;
};
