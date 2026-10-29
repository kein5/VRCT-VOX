import { atom, useAtom } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";
import { newerRoute } from "./routeState";

const settingsAtom = atom(null);
const statusAtom = atom({});
const routeAtom = atom({});
const devicesAtom = atom({ devices: [], error: null });
const errorAtom = atom(null);
const directStateAtom = atom({});
const directSourcesAtom = atom({ sources: [], error: null });
const directErrorAtom = atom(null);
const selectedSourceAtom = atom("");

export const useVoice = () => {
    const [settings, updateSettings] = useAtom(settingsAtom);
    const [status, setStatus] = useAtom(statusAtom);
    const updateStatus = useCallback(value => setStatus(previous => newerRoute(previous, value)), [setStatus]);
    const [route, setRoute] = useAtom(routeAtom);
    const updateRoute = useCallback(value => setRoute(previous => newerRoute(previous, value)), [setRoute]);
    const [devices, updateDevices] = useAtom(devicesAtom);
    const [error, updateError] = useAtom(errorAtom);
    const [directState, setDirectState] = useAtom(directStateAtom);
    const updateDirectState = useCallback(value => setDirectState(previous => newerRoute(previous, value)), [setDirectState]);
    const [directSources, updateDirectSources] = useAtom(directSourcesAtom);
    const [directError, updateDirectError] = useAtom(directErrorAtom);
    const [selectedSource, setSelectedSource] = useAtom(selectedSourceAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const send = useCallback(async (endpoint, data) => {
        if (endpoint.includes("direct_voice")) {
            if (endpoint !== "/get/data/direct_voice_state") updateDirectError(null);
            if (!await asyncStdoutToPython(endpoint, data)) updateDirectError("backend_unavailable");
            return;
        }
        if (endpoint === "/set/data/voice_settings" || endpoint === "/run/mute_voice" || endpoint === "/run/resume_voice") updateError(null);
        if (!await asyncStdoutToPython(endpoint, data)) updateError("backend_unavailable");
    }, [updateError, updateDirectError]);
    const reset = useCallback(() => {
        updateSettings(null); setStatus({}); setRoute({}); setDirectState({});
        setSelectedSource(""); updateDirectSources({ sources: [], error: null });
        updateError(null); updateDirectError(null);
    }, [updateSettings, setStatus, setRoute, setDirectState, setSelectedSource, updateDirectSources, updateError, updateDirectError]);
    return { settings, status, route, devices, error, send, reset, selectedSource, setSelectedSource, updateStatus, updateRoute, updateDevices, updateError,
        directState, directSources, directError, updateDirectState, updateDirectSources, updateDirectError,
        updateSettings: value => { updateSettings(value); updateError(null); } };
};
