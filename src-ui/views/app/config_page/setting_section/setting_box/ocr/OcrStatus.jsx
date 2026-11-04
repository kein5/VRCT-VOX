import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import { useOcr } from "@logics_configs";
import { captureStatusSummary } from "../../../../../../logics/configs/ocrReadiness";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import styles from "./Ocr.module.scss";

export const OcrStatus = ({ readiness, onRefresh }) => {
    const { t } = useI18n();
    const { currentOcrCaptureStatus, getOcrCaptureStatus } = useOcr();
    const getStatus = useRef(getOcrCaptureStatus);
    getStatus.current = getOcrCaptureStatus;
    useEffect(() => {
        getStatus.current();
        const timer = setInterval(() => getStatus.current(), 1000);
        return () => clearInterval(timer);
    }, []);
    const summary = captureStatusSummary(currentOcrCaptureStatus.data, readiness);
    const message = t(summary.key, summary.params);
    return (
        <EnvReadout className={styles.readiness} tone={summary.tone}
            actions={<button type="button" onClick={onRefresh}>{t("config_page.ocr.models.refresh")}</button>}>
            <p role="status">{summary.sourceKey ? t(summary.sourceKey, { status: message }) : message}</p>
        </EnvReadout>
    );
};
