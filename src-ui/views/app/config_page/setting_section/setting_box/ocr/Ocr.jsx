import { useCallback, useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import styles from "./Ocr.module.scss";

import { useOcr } from "@logics_configs";
import { useSaveButtonLogic } from "@logics_configs";
import {
    detectorStatus,
    FULL_REGION,
    isFullRegion,
    normalizeRegion,
    readinessSummary,
    regionPercent,
    withRegionValue,
} from "../../../../../../logics/configs/ocrReadiness";

import {
    CheckboxContainer,
    DropdownMenuContainer,
    EntryWithSaveButtonContainer,
    SliderContainer,
} from "../_templates/Templates";

import { SectionLabelComponent } from "../_components";
import { OcrModels } from "./OcrModels";

export const Ocr = () => {
    return (
        <div className={styles.container}>
            <Main_Container />
            <Detection_Container />
            <Advanced_Container />
        </div>
    );
};


const Main_Container = () => {
    const { t } = useI18n();
    const { currentOcrReadiness, getOcrReadiness, currentOcrSourceLanguage, currentOcrWindowTitle } = useOcr();
    // useOcr() hands out new functions on every render; pin the latest one so
    // refreshing does not itself trigger another refresh.
    const getReadiness = useRef(getOcrReadiness);
    getReadiness.current = getOcrReadiness;
    const refresh = useCallback(() => getReadiness.current(), []);
    const language = currentOcrSourceLanguage.data, title = currentOcrWindowTitle.data;
    // The models a language needs and whether VRChat is open change with these settings.
    useEffect(() => { refresh(); }, [refresh, language, title]);
    const readiness = currentOcrReadiness.data;
    const summary = readinessSummary(readiness);
    return (
        <div>
            <SectionLabelComponent label={t("config_page.ocr.section_title")} desc={t("config_page.ocr.section_desc")} />
            <div className={styles.readiness} data-ready={summary.ok}>
                <p role="status">{t(summary.key, summary.params)}</p>
                <button type="button" onClick={refresh}>{t("config_page.ocr.models.refresh")}</button>
            </div>
            <OcrSourceLanguage_Box />
            {readiness && readiness.required_models.length > 0 &&
                <OcrModels ids={readiness.required_models} missing={readiness.missing_models} onChanged={refresh}
                    title={t("config_page.ocr.models.title")} desc={t("config_page.ocr.models.desc")}
                    note={t("config_page.ocr.models.required")} />}
        </div>
    );
};

const Detection_Container = () => {
    const { t } = useI18n();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.ocr.detection")} />
            <OcrChatboxDetector_Box />
            <OcrCaptureRegion_Box />
            <OcrChatboxFilter_Box />
        </div>
    );
};

// VRCT-VOX's own chatbox detector: optional download, then a switch (on by default).
const OcrChatboxDetector_Box = () => {
    const { t } = useI18n();
    const { currentOcrReadiness, getOcrReadiness, currentOcrUseChatboxDetector, toggleOcrUseChatboxDetector } = useOcr();
    const getReadiness = useRef(getOcrReadiness);
    getReadiness.current = getOcrReadiness;
    const refresh = useCallback(() => getReadiness.current(), []);
    const readiness = currentOcrReadiness.data;
    const status = detectorStatus(readiness, currentOcrUseChatboxDetector.data);
    if (!status) return null;
    return (
        <div className={styles.detector}>
            <CheckboxContainer
                setting_id="ocr_use_chatbox_detector"
                label={t("config_page.ocr.detector.label")}
                desc={t("config_page.ocr.detector.desc")}
                variable={{ ...currentOcrUseChatboxDetector, data: status.on }}
                is_available={status.installed}
                toggleFunction={status.installed ? toggleOcrUseChatboxDetector : undefined}
            />
            <p role="status" className={styles.detectorStatus} data-state={status.on ? "on" : "off"}>{t(status.key)}</p>
            {!status.installed &&
                <OcrModels ids={[status.model]} missing={[status.model]} onChanged={refresh}
                    title={t("config_page.ocr.detector.models_title")} note={t("config_page.ocr.detector.optional")} />}
        </div>
    );
};

const OcrCaptureRegion_Box = () => {
    const { t } = useI18n();
    const { currentOcrCaptureRegion, setOcrCaptureRegion } = useOcr();
    const region = normalizeRegion(currentOcrCaptureRegion.data);
    const slider = (key) => (
        <SliderContainer
            key={key}
            label={t(`config_page.ocr.region.${key}`)}
            variable={regionPercent(region, key)}
            setterFunction={(value) => setOcrCaptureRegion(withRegionValue(region, key, value))}
            min={key === "width" || key === "height" ? 2 : 0}
            max={100}
            step={1}
            show_label_values={[0, 25, 50, 75, 100]}
            valueLabelFormat={(v) => `${v}%`}
        />
    );
    return (
        <div className={styles.region}>
            <div className={styles.regionHeader}>
                <div>
                    <p className={styles.regionLabel}>{t("config_page.ocr.region.label")}</p>
                    <p className={styles.regionDesc}>{t("config_page.ocr.region.desc")}</p>
                </div>
                <div className={styles.preview} role="img" aria-label={t("config_page.ocr.region.preview_label")}>
                    <div className={styles.previewArea} style={{
                        left: `${region.x * 100}%`, top: `${region.y * 100}%`,
                        width: `${region.width * 100}%`, height: `${region.height * 100}%`,
                    }} />
                </div>
            </div>
            {["x", "y", "width", "height"].map(slider)}
            <button type="button" className={styles.resetButton} disabled={isFullRegion(region)}
                onClick={() => setOcrCaptureRegion({ ...FULL_REGION })}>{t("config_page.ocr.region.reset")}</button>
        </div>
    );
};

const OcrChatboxFilter_Box = () => {
    const { t } = useI18n();
    const { currentOcrChatboxFilter, toggleOcrChatboxFilter } = useOcr();
    return (
        <CheckboxContainer
            setting_id="ocr_chatbox_filter"
            label={t("config_page.ocr.chatbox_filter.label")}
            desc={t("config_page.ocr.chatbox_filter.desc")}
            variable={currentOcrChatboxFilter}
            toggleFunction={toggleOcrChatboxFilter}
        />
    );
};

const OcrSourceLanguage_Box = () => {
    const { t } = useI18n();
    const { currentSelectableOcrSourceLanguageList, currentOcrSourceLanguage, setOcrSourceLanguage } = useOcr();

    const selectFunction = (selected_data) => {
        setOcrSourceLanguage(selected_data.selected_id);
    };

    return (
        <DropdownMenuContainer
            dropdown_id="ocr_source_language"
            label={t("config_page.ocr.source_language.label")}
            desc={t("config_page.ocr.source_language.desc")}
            selected_id={currentOcrSourceLanguage.data}
            list={currentSelectableOcrSourceLanguageList.data}
            selectFunction={selectFunction}
            state={currentOcrSourceLanguage.state}
            remove_border_bottom={true}
        />
    );
};


const Advanced_Container = () => {
    return (
        <>
            <CaptureTarget_Container />
            <Performance_Container />
        </>
    );
};

const CaptureTarget_Container = () => {
    const { t } = useI18n();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.ocr.capture_target")} />
            <OcrWindowTitle_Box />
        </div>
    );
};

const Performance_Container = () => {
    const { t } = useI18n();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.ocr.performance")} />
            <OcrPollIntervalMs_Box />
            <OcrMinConfidence_Box />
            <OcrBubbleMinTextLength_Box />
        </div>
    );
};

const OcrWindowTitle_Box = () => {
    const { t } = useI18n();
    const { currentOcrWindowTitle, setOcrWindowTitle } = useOcr();

    const { variable, onChangeFunction, saveFunction } = useSaveButtonLogic({
        variable: currentOcrWindowTitle.data,
        state: currentOcrWindowTitle.state,
        setFunction: setOcrWindowTitle,
    });

    return (
        <EntryWithSaveButtonContainer
            label={t("config_page.ocr.window_title.label")}
            desc={t("config_page.ocr.window_title.desc")}
            variable={variable}
            saveFunction={saveFunction}
            onChangeFunction={onChangeFunction}
            state={currentOcrWindowTitle.state}
            width="16rem"
            remove_border_bottom={true}
        />
    );
};

const OcrPollIntervalMs_Box = () => {
    const { t } = useI18n();
    const { currentOcrPollIntervalMs, setOcrPollIntervalMs } = useOcr();

    return (
        <SliderContainer
            label={t("config_page.ocr.poll_interval_ms.label")}
            desc={t("config_page.ocr.poll_interval_ms.desc")}
            variable={currentOcrPollIntervalMs.data}
            setterFunction={setOcrPollIntervalMs}
            min={100}
            max={5000}
            step={50}
            show_label_values={[100, 1000, 2000, 3000, 4000, 5000]}
            valueLabelFormat={(v) => `${v} ms`}
        />
    );
};

const OcrMinConfidence_Box = () => {
    const { t } = useI18n();
    const { currentOcrMinConfidence, setOcrMinConfidence } = useOcr();

    return (
        <SliderContainer
            label={t("config_page.ocr.min_confidence.label")}
            desc={t("config_page.ocr.min_confidence.desc")}
            variable={currentOcrMinConfidence.data}
            setterFunction={setOcrMinConfidence}
            min={0.1}
            max={0.99}
            step={0.01}
            marks_step={0.1}
            show_label_values={[0.1, 0.3, 0.5, 0.7, 0.9]}
        />
    );
};

const OcrBubbleMinTextLength_Box = () => {
    const { t } = useI18n();
    const { currentOcrBubbleMinTextLength, setOcrBubbleMinTextLength } = useOcr();

    return (
        <SliderContainer
            label={t("config_page.ocr.bubble_min_text_length.label")}
            desc={t("config_page.ocr.bubble_min_text_length.desc")}
            variable={currentOcrBubbleMinTextLength.data}
            setterFunction={setOcrBubbleMinTextLength}
            min={1}
            max={50}
            step={1}
            show_label_values={[1, 10, 20, 30, 40, 50]}
            remove_border_bottom={true}
        />
    );
};
