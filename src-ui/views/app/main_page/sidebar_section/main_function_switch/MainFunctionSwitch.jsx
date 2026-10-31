import { useEffect } from "react";
import { useVoice, sourceKey } from "../../../../../logics/voice/useVoice";
import { useNotificationStatus } from "../../../../../logics/common/useNotificationStatus";
import { useI18n } from "@useI18n";
import clsx from "clsx";
import styles from "./MainFunctionSwitch.module.scss";
import TranslationSvg from "@images/translation.svg?react";
import MicSvg from "@images/mic.svg?react";
import HeadphonesSvg from "@images/headphones.svg?react";
import ChatTranscribeSvg from "@images/chat_transcribe.svg?react";
import {
    useIsMainPageCompactMode,
    useMainFunction,
} from "@logics_main";
import { ToggleSwitch } from "../../../../common_components/toggle_switch/ToggleSwitch";

export const MainFunctionSwitch = () => {
    const { t, i18n } = useI18n();

    const {
        toggleTranslation, currentTranslationStatus,
        toggleTranscriptionSend, currentTranscriptionSendStatus,
        toggleTranscriptionReceive, currentTranscriptionReceiveStatus,
        toggleOcrCapture, currentOcrCaptureStatus,
    } = useMainFunction();


    const voice = useVoice();
    const { showNotification_Error } = useNotificationStatus();
    // Known codes get their next step; the code stays visible for support.
    const notify = (code, page) => {
        const key = `voice_ui.errors.${code}`;
        showNotification_Error(/^[a-z0-9_]+$/.test(code) && i18n.exists(key)
            ? `${t(key)} (${code})` : `${code} · ${t("voice_ui.check_settings", { page })}`);
    };
    useEffect(() => { if (voice.ttsError) notify(voice.ttsError, "TTS"); }, [voice.ttsError]);
    useEffect(() => { if (voice.directError) notify(voice.directError, "RVC"); }, [voice.directError]);
    const rvcOwnsInput = voice.directOwner === "rvc";
    useEffect(() => {
        if (rvcOwnsInput && voice.directState.error) notify(voice.directState.error, "RVC");
    }, [rvcOwnsInput, voice.directState.error]);
    const toggleTts = () => {
        if (voice.ttsPending?.intent === false) return;
        if (voice.status.tts_enabled || voice.ttsPending?.intent) return voice.send("/run/disable_tts");
        if (!Number.isSafeInteger(voice.status.tts_generation)) return notify(t("voice_ui.state_unknown"), "TTS");
        voice.send("/run/enable_tts", { generation: voice.status.tts_generation });
    };
    const toggleRvc = () => {
        if (rvcOwnsInput && voice.directPending?.intent === false) return;
        if (rvcOwnsInput && (voice.directState.requested || voice.directState.pending || voice.directPending?.intent))
            return voice.send("/run/stop_direct_voice");
        if (voice.directPending || voice.directState.requested || voice.directState.pending || voice.directState.stopping)
            return notify(t("voice_ui.input_conflict"), "RVC");
        if (voice.directDraftBlocked) return notify(t("voice_ui.save_direct_first"), "RVC");
        const cfg = voice.directState.settings;
        const source = voice.directSources.sources?.find(item => sourceKey(item.id) === voice.selectedSource);
        if (voice.settings?.routing !== "managed" || !voice.directState.observation_id ||
            voice.directSources.error || !source || cfg?.mode !== "converted" || cfg?.engine !== "rvc" ||
            !cfg.rvc_runtime || !cfg.rvc_model) return notify(t("voice_ui.rvc_not_ready"), "RVC");
        voice.send("/run/start_direct_voice", { source: source.id, mode: "converted", options: {
            engine: "rvc", runtime: cfg.rvc_runtime, model: cfg.rvc_model, index: cfg.rvc_index,
            pitch: cfg.rvc_pitch, index_rate: cfg.rvc_index_rate,
        } });
    };
    const switch_items = [
        {
            switch_id: "translation",
            label: t("main_page.translation"),
            SvgComponent: TranslationSvg,
            currentState: currentTranslationStatus,
            toggleFunction: toggleTranslation,
        },
        {
            switch_id: "transcription_send",
            label: t("main_page.transcription_send"),
            SvgComponent: MicSvg,
            currentState: currentTranscriptionSendStatus,
            toggleFunction: toggleTranscriptionSend,
        },
        {
            switch_id: "transcription_receive",
            label: t("main_page.transcription_receive"),
            SvgComponent: HeadphonesSvg,
            currentState: currentTranscriptionReceiveStatus,
            toggleFunction: toggleTranscriptionReceive,
        },
        {
            switch_id: "ocr",
            label: t("main_page.ocr"),
            SvgComponent: ChatTranscribeSvg,
            currentState: currentOcrCaptureStatus,
            toggleFunction: toggleOcrCapture,
        },
        { switch_id: "tts", label: "TTS", SvgComponent: HeadphonesSvg, toggleFunction: toggleTts, cancellable: true, disabled: !Number.isSafeInteger(voice.status.tts_generation),
          statusText: voice.ttsPending?.intent && voice.status.tts_server_starting === true ? t("voice_ui.tts_server_starting") : null,
          currentState: { data: voice.status.tts_enabled === true, state: voice.ttsPending || voice.status.tts_stopping ? "pending" : "ok" } },
        { switch_id: "rvc", label: "RVC", SvgComponent: MicSvg, toggleFunction: toggleRvc, cancellable: true, disabled: !voice.directState.observation_id,
          currentState: { data: rvcOwnsInput && !!voice.directState.requested,
            state: rvcOwnsInput && (voice.directPending || voice.directState.pending || voice.directState.stopping) ? "pending" : "ok" } },
    ];

    return (
        <div className={styles.container}>
            {switch_items.map(item => (
                <SwitchContainer
                    key={item.switch_id}
                    switch_id={item.switch_id}
                    cancellable={item.cancellable}
                    disabled={item.disabled}
                    switchLabel={item.label}
                    currentState={item.currentState}
                    statusText={item.statusText}
                    toggleFunction={item.toggleFunction}
                    SvgComponent={item.SvgComponent}
                >
                </SwitchContainer>
            ))}
        </div>
    );
};

export const SwitchContainer = ({ switchLabel, switch_id, children, currentState, toggleFunction, SvgComponent, cancellable = false, disabled = false, statusText = null }) => {
    const { currentIsMainPageCompactMode } = useIsMainPageCompactMode();

    const getClassNames = (baseClass) => clsx(baseClass, {
        [styles.is_compact_mode]: currentIsMainPageCompactMode.data,
        [styles.is_active]: (currentState.data === true),
        [styles.is_pending]: (currentState.state === "pending"),
        [styles.cancellable]: cancellable,
    });

    return (
        <div
            className={getClassNames(styles.switch_container)}
            role="switch" aria-label={switchLabel} aria-checked={currentState.data === true}
            aria-busy={currentState.state === "pending"} aria-disabled={disabled} tabIndex={0}
            title={statusText ?? undefined}
            onClick={() => { if (!disabled) toggleFunction(); }}
            onKeyDown={event => {
                if (event.key === " " || event.key === "Enter") {
                    event.preventDefault();
                    if (!disabled && (cancellable || currentState.state !== "pending")) toggleFunction();
                }
            }}
        >
            <div className={styles.label_wrapper}>
                <SvgComponent className={getClassNames(styles.switch_svg)} />
                <p className={getClassNames(styles.switch_label)}>{switchLabel}</p>
                {statusText && <span className={getClassNames(styles.switch_status)} role="status">{statusText}</span>}
                {children}
            </div>

            <ToggleSwitch
                isActive={currentState.data === true}
                isPending={currentState.state === "pending"}
                className={getClassNames(styles.toggle_control)}
            />

            <div className={getClassNames(styles.switch_indicator)}></div>
            {(currentState.state === "pending") && (
                <span className={styles.loader}></span>
            )}
        </div>
    );
};
