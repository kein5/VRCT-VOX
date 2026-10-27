import { atom, useAtom } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";
import { newerRoute } from "./routeState";

const settingsAtom = atom(null);
const statusAtom = atom({});
const routeAtom = atom({});
const devicesAtom = atom({ devices: [], error: null });
const errorAtom = atom(null);

export const useVoice = () => {
    const [settings, updateSettings] = useAtom(settingsAtom);
    const [status, updateStatus] = useAtom(statusAtom);
    const [route, setRoute] = useAtom(routeAtom);
    const updateRoute = useCallback(value => setRoute(previous => newerRoute(previous, value)), [setRoute]);
    const [devices, updateDevices] = useAtom(devicesAtom);
    const [error, updateError] = useAtom(errorAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const send = useCallback(async (endpoint, data) => {
        if (endpoint === "/set/data/voice_settings" || endpoint === "/run/mute_voice" || endpoint === "/run/resume_voice") updateError(null);
        if (!await asyncStdoutToPython(endpoint, data)) updateError("backend_unavailable");
    }, [updateError]);
    return { settings, status, route, devices, error, send, updateStatus, updateRoute, updateDevices, updateError,
        updateSettings: value => { updateSettings(value); updateError(null); } };
};
