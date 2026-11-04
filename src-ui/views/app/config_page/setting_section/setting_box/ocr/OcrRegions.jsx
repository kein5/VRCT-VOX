import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import { useOcr } from "@logics_configs";
import { FULL_REGION, isFullRegion, normalizeRegion, regionPercent, withRegionValue,
    captureSourceSummary } from "../../../../../../logics/configs/ocrReadiness";
import { SliderContainer } from "../_templates/Templates";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import styles from "./Ocr.module.scss";

export const OcrRegions = () => {
    const { t } = useI18n();
    const { currentOcrCaptureStatus, getOcrCaptureStatus, currentOcrCaptureRegion, setOcrCaptureRegion,
        currentOcrVrCaptureRegion, setOcrVrCaptureRegion } = useOcr();
    const getStatus = useRef(getOcrCaptureStatus);
    getStatus.current = getOcrCaptureStatus;
    useEffect(() => {
        getStatus.current();
        const timer = setInterval(() => getStatus.current(), 1000);
        return () => clearInterval(timer);
    }, []);
    const status = currentOcrCaptureStatus.data;
    const summary = captureSourceSummary(status);
    const hasVr = status?.available_sources?.includes("vr") === true;
    return (
        <div>
            <EnvReadout className={styles.readiness} tone={summary.active ? "active" : "neutral"}>
                <p>{t(summary.key)}</p>
            </EnvReadout>
            {hasVr && <p className={styles.regionDesc}>{t("config_page.ocr.region.source_switch")}</p>}
            <OcrRegionEditor source="window" variable={currentOcrCaptureRegion} setRegion={setOcrCaptureRegion} />
            {hasVr && <OcrRegionEditor source="vr" variable={currentOcrVrCaptureRegion} setRegion={setOcrVrCaptureRegion} />}
        </div>
    );
};

export const OcrRegionEditor = ({ source, variable, setRegion }) => {
    const { t } = useI18n();
    const region = normalizeRegion(variable.data);
    const label = t(`config_page.ocr.region.${source}_label`);
    const slider = key => (
        <SliderContainer
            key={key}
            label={t(`config_page.ocr.region.${key}`)}
            state={variable.state}
            variable={regionPercent(region, key)}
            setterFunction={value => setRegion(withRegionValue(region, key, value))}
            min={key === "width" || key === "height" ? 2 : 0}
            max={100}
            step={1}
            show_label_values={[0, 25, 50, 75, 100]}
            valueLabelFormat={v => `${v}%`}
        />
    );
    return (
        <section className={styles.region} aria-label={label}>
            <div className={styles.regionHeader}>
                <div>
                    <p className={styles.regionLabel}>{label}</p>
                    <p className={styles.regionDesc}>{t(`config_page.ocr.region.${source === "vr" ? "vr_desc" : "desc"}`)}</p>
                </div>
                <div className={styles.preview} role="img"
                    aria-label={t(`config_page.ocr.region.${source === "vr" ? "vr_preview_label" : "preview_label"}`)}>
                    <div className={styles.previewArea} style={{
                        left: `${region.x * 100}%`, top: `${region.y * 100}%`,
                        width: `${region.width * 100}%`, height: `${region.height * 100}%`,
                    }} />
                </div>
            </div>
            {["x", "y", "width", "height"].map(slider)}
            <button type="button" className={styles.resetButton}
                disabled={isFullRegion(region) || variable.state !== "ok"}
                onClick={() => setRegion({ ...FULL_REGION })}>
                {t(`config_page.ocr.region.${source === "vr" ? "vr_reset" : "reset"}`)}
            </button>
        </section>
    );
};
