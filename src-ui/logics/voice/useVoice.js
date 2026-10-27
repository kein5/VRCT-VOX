import { atom, useAtom } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";

const settingsAtom = atom(null);
const statusAtom = atom({});
const devicesAtom = atom({ devices: [], error: null });
const errorAtom = atom(null);

export const useVoice = () => {
    const [settings, updateSettings] = useAtom(settingsAtom);
    const [status, updateStatus] = useAtom(statusAtom);
    const [devices, updateDevices] = useAtom(devicesAtom);
    const [error, updateError] = useAtom(errorAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const send = useCallback(async (endpoint, data) => {
        if (endpoint === "/set/data/voice_settings") updateError(null);
        if (!await asyncStdoutToPython(endpoint, data)) updateError("backend_unavailable");
    }, [updateError]);
    return { settings, status, devices, error, send, updateStatus, updateDevices, updateError,
        updateSettings: value => { updateSettings(value); updateError(null); } };
};
