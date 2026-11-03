import {
    Atom_MicVolume,
    Atom_SpeakerVolume,
    useStore_MicThresholdCheckStatus,
    useStore_SpeakerThresholdCheckStatus,
} from "@store";

import { useStdoutToPython } from "@useStdoutToPython";
import { useSetAtom } from "jotai";
import { updateMeterValue } from "./meterValue.js";

export const useVolume = () => {
    const { asyncStdoutToPython } = useStdoutToPython();
    const setMicVolume = useSetAtom(Atom_MicVolume);
    const setSpeakerVolume = useSetAtom(Atom_SpeakerVolume);
    const updateMicVolume = value => setMicVolume(previous => updateMeterValue(previous, value));
    const updateSpeakerVolume = value => setSpeakerVolume(previous => updateMeterValue(previous, value));
    const {
        currentMicThresholdCheckStatus,
        updateMicThresholdCheckStatus,
        pendingMicThresholdCheckStatus,
    } = useStore_MicThresholdCheckStatus();
    const {
        currentSpeakerThresholdCheckStatus,
        updateSpeakerThresholdCheckStatus,
        pendingSpeakerThresholdCheckStatus,
    } = useStore_SpeakerThresholdCheckStatus();

    return {
        volumeCheckStart_Mic: () => {
            pendingMicThresholdCheckStatus();
            asyncStdoutToPython("/set/enable/check_mic_threshold");
        },
        volumeCheckStop_Mic: () => {
            pendingMicThresholdCheckStatus();
            asyncStdoutToPython("/set/disable/check_mic_threshold");
        },
        updateVolumeVariable_Mic: (payload) => {
            updateMicVolume(payload);
        },
        currentMicThresholdCheckStatus: currentMicThresholdCheckStatus,
        updateMicThresholdCheckStatus: (payload) => {
            updateMicThresholdCheckStatus(payload);
            if (payload === false) updateMicVolume("0");
        },

        volumeCheckStart_Speaker: () => {
            updateSpeakerVolume("0");
            pendingSpeakerThresholdCheckStatus();
            asyncStdoutToPython("/set/enable/check_speaker_threshold");
        },
        volumeCheckStop_Speaker: () => {
            pendingSpeakerThresholdCheckStatus();
            asyncStdoutToPython("/set/disable/check_speaker_threshold");
        },
        updateVolumeVariable_Speaker: (payload) => {
            updateSpeakerVolume(payload);
        },
        currentSpeakerThresholdCheckStatus: currentSpeakerThresholdCheckStatus,
        updateSpeakerThresholdCheckStatus: (payload) => {
            updateSpeakerThresholdCheckStatus(payload);
            if (payload === false) updateSpeakerVolume("0");
        }

    };
};
