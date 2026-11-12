import { useEffect } from "react";

import {
    useVolume,
    useIsOpenedConfigPage,
} from "@logics_common";

import {
    useMainFunction,
} from "@logics_main";

import { useStore_MainFunctionsStateMemory } from "@store";

export const ConfigPageCloseTriggerController = () => {
    const { currentIsOpenedConfigPage } = useIsOpenedConfigPage();
    const {
        currentMainFunctionsStateMemory,
        updateMainFunctionsStateMemory,
    } = useStore_MainFunctionsStateMemory();

    const {
        currentTranslationStatus,
        setTranslation,
        pendingTranslationStatus,
        currentTranscriptionSendStatus,
        setTranscriptionSend,
        pendingTranscriptionSendStatus,
        currentTranscriptionReceiveStatus,
        setTranscriptionReceive,
        pendingTranscriptionReceiveStatus,
    } = useMainFunction();
    const {
        currentMicThresholdCheckStatus,
        volumeCheckStop_Mic,
        currentSpeakerThresholdCheckStatus,
        volumeCheckStop_Speaker,
    } = useVolume();

    const memorizeLatestMainFunctionsState = () => {
        updateMainFunctionsStateMemory({
            translation: currentTranslationStatus.data,
            transcription_send: currentTranscriptionSendStatus.data,
            transcription_receive: currentTranscriptionReceiveStatus.data,
        });
    };

    const restoreMainFunctionState = () => {
        // First, set loading status all before waiting a backend process.
        if (currentMainFunctionsStateMemory.data.translation === true) pendingTranslationStatus();
        if (currentMainFunctionsStateMemory.data.transcription_send === true) pendingTranscriptionSendStatus();
        if (currentMainFunctionsStateMemory.data.transcription_receive === true) pendingTranscriptionReceiveStatus();

        // Then, restore them.
        if (currentMainFunctionsStateMemory.data.translation === true) setTranslation(true);
        // The engine declines this resume if the user stopped the bundled ASR
        // server while settings were open: leaving settings must not start again
        // what they stopped. It answers "off" and the switch shows it.
        if (currentMainFunctionsStateMemory.data.transcription_send === true) setTranscriptionSend(true, { reason: "settings_resume" });
        if (currentMainFunctionsStateMemory.data.transcription_receive === true) setTranscriptionReceive(true, { reason: "settings_resume" });
    };

    useEffect(() => {
        if (currentIsOpenedConfigPage.data === true) { // When config page is opened.
            memorizeLatestMainFunctionsState();
            if (currentTranslationStatus.data === true) setTranslation(false);
            if (currentTranscriptionSendStatus.data === true) setTranscriptionSend(false, { reason: "settings_pause" });
            if (currentTranscriptionReceiveStatus.data === true) setTranscriptionReceive(false, { reason: "settings_pause" });
        } else if (currentIsOpenedConfigPage.data === false) { // When config page is closed.
            if (currentMicThresholdCheckStatus.data === true) volumeCheckStop_Mic();
            if (currentSpeakerThresholdCheckStatus.data === true) volumeCheckStop_Speaker();
            restoreMainFunctionState();
        }
    }, [currentIsOpenedConfigPage.data]);
    return null;
};
