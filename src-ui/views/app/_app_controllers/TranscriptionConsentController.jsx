import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { useTranscription } from "@logics_configs";
import { useMainFunction } from "@logics_main";
import { useStore_IsOpenedConfigPage, useStore_SelectedConfigTabId } from "@store";
import { useTranscriptionConsent } from "../../../logics/transcription/useTranscriptionConsent";
import { useConsentDialog } from "../../../logics/common/useConsentDialog";
import { LegacyModelDownloadDialog } from "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog";
import styles from "../config_page/setting_section/setting_box/advanced_settings/VoiceSettings.module.scss";
import dialogStyles from "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog.module.scss";

export const TranscriptionConsentController = () => {
    const { t } = useI18n();
    const { request, setRequest } = useTranscriptionConsent();
    const { currentSelectedTranscriptionEngine, setSelectedTranscriptionEngine,
        currentSelectedWhisperWeightType, pendingWhisperWeightTypeStatus, downloadWhisperWeightTypeStatus } = useTranscription();
    const { setTranscriptionSend, setTranscriptionReceive } = useMainFunction();
    const { updateIsOpenedConfigPage } = useStore_IsOpenedConfigPage();
    const { updateSelectedConfigTabId } = useStore_SelectedConfigTabId();
    const { dialog, close } = useConsentDialog(!!request && request.mode !== "download");
    const selection = useRef(null);
    const [choice, setChoice] = useState(null);
    const cancel = () => { selection.current = null; setChoice(null); close(); setRequest(null); };

    useEffect(() => () => { selection.current = null; setRequest(null); }, [setRequest]);
    useEffect(() => {
        const waiting = selection.current;
        if (!waiting || request !== waiting.request || currentSelectedTranscriptionEngine.state !== "ok") return;
        // A write being sent is not an acknowledgement. Continue only after the
        // saved selection comes back through the ordinary settings response.
        if (currentSelectedTranscriptionEngine.data !== waiting.engine) {
            selection.current = null;
            return;
        }
        selection.current = null;
        close();
        if (waiting.engine === "Google") {
            setRequest(null);
            (request.endpoint.endsWith("_send") ? setTranscriptionSend : setTranscriptionReceive)(true);
        } else {
            setRequest({ ...request, mode: "download" });
        }
    }, [request, choice, currentSelectedTranscriptionEngine.data, currentSelectedTranscriptionEngine.state]);

    if (!request) return null;
    const choose = async engine => {
        if (selection.current) return;
        const waiting = { engine, request };
        selection.current = waiting;
        setChoice(waiting);
        const sent = await setSelectedTranscriptionEngine(engine);
        if (sent === false && selection.current === waiting) selection.current = null;
    };
    if (request.mode === "download") return <LegacyModelDownloadDialog kind="whisper"
        weightType={currentSelectedWhisperWeightType.data} onCancel={cancel} onDownload={payload => {
            pendingWhisperWeightTypeStatus(payload.weight_type);
            downloadWhisperWeightTypeStatus(payload);
        }} />;
    const pending = currentSelectedTranscriptionEngine.state === "pending";
    return <div className={`${styles.container} ${dialogStyles.host}`}>
        <dialog ref={dialog} className={dialogStyles.dialog} aria-label={t("transcription_consent.title")}
            onCancel={event => { event.preventDefault(); cancel(); }}>
            <h3>{t("transcription_consent.title")}</h3>
            {request.mode === "choose" ? <>
                <p>{t("transcription_consent.google_notice")}</p>
                <p>{t("transcription_consent.whisper_notice")}</p>
                <div className={styles.actions}>
                    <button type="button" autoFocus onClick={cancel}>{t("transcription_consent.cancel")}</button>
                    <button type="button" disabled={pending} onClick={() => choose("Google")}>{t("transcription_consent.google")}</button>
                    <button type="button" disabled={pending} onClick={() => choose("Whisper")}>{t("transcription_consent.whisper")}</button>
                </div>
            </> : <>
                <p>{t("backend_errors.TRANSCRIPTION_ENGINE_UNAVAILABLE")}</p>
                <div className={styles.actions}>
                    <button type="button" autoFocus onClick={cancel}>{t("transcription_consent.cancel")}</button>
                    <button type="button" onClick={() => {
                        cancel(); updateSelectedConfigTabId("transcription"); updateIsOpenedConfigPage(true);
                    }}>{t("transcription_consent.settings")}</button>
                </div>
            </>}
        </dialog>
    </div>;
};
