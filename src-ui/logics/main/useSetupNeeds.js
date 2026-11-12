import { useTranslation, useTranscription } from "@logics_configs";
import { useStore_IsBackendReady, useStore_SelectedPresetTabNumber, useStore_SelectedTranslationEngines } from "@store";
import { setupNeeds } from "./setupNeeds";
import { useTranslationSetup } from "../translation/useTranslationSetup";
import { useTranscriptionConsent } from "../transcription/useTranscriptionConsent";

// The setup the selected engines still need, and how to start each one.
// Both open the same review (provider, license, size, consent) settings use.
export const useSetupNeeds = () => {
    const { currentIsBackendReady } = useStore_IsBackendReady();
    const { currentSelectedPresetTabNumber } = useStore_SelectedPresetTabNumber();
    const { currentSelectedTranslationEngines } = useStore_SelectedTranslationEngines();
    const { currentCTranslate2WeightTypeStatus, currentSelectedCTranslate2WeightType } = useTranslation();
    const { currentSelectedTranscriptionEngine, currentWhisperWeightTypeStatus, currentSelectedWhisperWeightType } = useTranscription();
    const translationSetup = useTranslationSetup();
    const transcriptionConsent = useTranscriptionConsent();
    // Until the engine has sent its settings, "not downloaded" is only the list's default.
    const needs = currentIsBackendReady.data !== true ? [] : setupNeeds({
        translationEngine: currentSelectedTranslationEngines.data?.[currentSelectedPresetTabNumber.data],
        translationWeights: currentCTranslate2WeightTypeStatus.data,
        translationWeight: currentSelectedCTranslate2WeightType.data,
        transcriptionEngine: currentSelectedTranscriptionEngine.data,
        whisperWeights: currentWhisperWeightTypeStatus.data,
        whisperWeight: currentSelectedWhisperWeightType.data,
    });
    const start = id => id === "translation" ? translationSetup.open(false)
        : transcriptionConsent.setRequest(previous => previous ?? { endpoint: "/set/enable/transcription_send", mode: "download", resume: false });
    return { needs, start };
};
