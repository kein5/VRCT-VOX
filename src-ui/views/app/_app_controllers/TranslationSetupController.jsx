import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import { useTranslation } from "@logics_configs";
import { useMainFunction } from "@logics_main";
import { useNotificationStatus } from "@logics_common";
import { useStore_IsOpenedTranslatorSelector } from "@store";
import { useTranslationSetup } from "../../../logics/translation/useTranslationSetup";
import { downloadProgress } from "../../../logics/main/setupNeeds";
import { LegacyModelDownloadDialog } from "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog";

// Turning Translation on without its model used to fail with a notice that
// named a settings path and vanished. The same review settings use (provider,
// license, size, consent) now opens where the user is. When they pressed the
// switch to get here, the switch is turned on once the model has arrived.
export const TranslationSetupController = () => {
    const { t } = useI18n();
    const { request, setRequest } = useTranslationSetup();
    const { currentCTranslate2WeightTypeStatus, currentSelectedCTranslate2WeightType,
        pendingCTranslate2WeightTypeStatus, downloadCTranslate2WeightTypeStatus } = useTranslation();
    const { currentTranslationStatus, setTranslation } = useMainFunction();
    const { showNotification_Success } = useNotificationStatus();
    const { updateIsOpenedTranslatorSelector } = useStore_IsOpenedTranslatorSelector();
    // The model whose arrival turns the switch on; null when nobody is waiting.
    const waiting = useRef(null);

    useEffect(() => () => { waiting.current = null; setRequest(null); }, [setRequest]);
    const weights = currentCTranslate2WeightTypeStatus.data || [];
    const awaited = weights.find(item => item.id === waiting.current);
    const arrived = awaited?.is_downloaded === true;
    const abandoned = !!awaited && !arrived && downloadProgress(awaited) === null;
    useEffect(() => {
        if (!waiting.current) return;
        if (arrived) {
            waiting.current = null;
            showNotification_Success(t("studio.setup_translation_ready"), { category_id: "translation_setup_ready" });
            if (currentTranslationStatus.data !== true) setTranslation(true);
        } else if (abandoned) {
            waiting.current = null;  // cancelled or failed; its own notice says why
        }
    }, [arrived, abandoned]);

    if (!request) return null;
    const close = () => setRequest(null);
    return <LegacyModelDownloadDialog kind="ctranslate2" weightType={currentSelectedCTranslate2WeightType.data}
        onCancel={close}
        onDownload={payload => {
            waiting.current = request.resume ? payload.weight_type : null;
            pendingCTranslate2WeightTypeStatus(payload.weight_type);
            downloadCTranslate2WeightTypeStatus(payload);
        }}
        note={request.resume ? t("studio.setup_translation_resume") : null}
        extraAction={{ label: t("studio.setup_other_translator"), onClick: () => updateIsOpenedTranslatorSelector(true) }} />;
};
