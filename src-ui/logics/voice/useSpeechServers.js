import { atom, useAtom, useStore } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";
import { sameValue } from "../common/polledState.js";

const settingsAtom = atom(null), stateAtom = atom({}), pendingAtom = atom({}), errorAtom = atom(null), devicesAtom = atom([]);
const phases = { stopped: 0, preparing: 1, ready: 2, stopping: 3, failed: 4 };
const profiles = ["japanese", "multilingual", "asr"];

export const useSpeechServers = () => {
    const atoms = useStore();
    const [settings, setSettings] = useAtom(settingsAtom);
    const [state] = useAtom(stateAtom);
    const [devices, setDevices] = useAtom(devicesAtom);
    const [pending] = useAtom(pendingAtom);
    const [error, setError] = useAtom(errorAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const updateError = useCallback(value => {
        setError(value);
        if (value) atoms.set(pendingAtom, {});
    }, [atoms, setError]);
    const updateSettings = useCallback(value => { setSettings(value); setError(null); }, [setSettings, setError]);
    const updateDevices = useCallback(value => { if (Array.isArray(value?.devices)) setDevices(value.devices); }, [setDevices]);
    const updateState = useCallback(value => {
        const current = atoms.get(stateAtom), pending = atoms.get(pendingAtom);
        let next = current, waiting = pending;
        for (const name of profiles) {
            const row = value?.[name], previous = next[name];
            if (!Number.isSafeInteger(row?.generation) || row.generation < 0 || !(row.state in phases)) continue;
            if (previous && (row.generation < previous.generation ||
                (row.generation === previous.generation && phases[row.state] < phases[previous.state]))) continue;
            if (!sameValue(previous, row)) {
                if (next === current) next = { ...current };
                next[name] = row;
            }
            if (waiting[name] && row.generation > waiting[name].generation) {
                if (waiting === pending) waiting = { ...pending };
                delete waiting[name];
            }
        }
        atoms.set(stateAtom, next);
        atoms.set(pendingAtom, waiting);
    }, [atoms]);
    const backendStopped = useCallback(() => {
        updateError("backend_unavailable");
        atoms.set(stateAtom, value => Object.fromEntries(Object.entries(value).map(([name, row]) =>
            [name, { ...row, state: "failed", error_code: "backend_unavailable" }])));
    }, [atoms, updateError]);
    const reset = useCallback(() => {
        atoms.set(settingsAtom, null);
        atoms.set(stateAtom, {});
        atoms.set(pendingAtom, {});
        atoms.set(errorAtom, null);
        atoms.set(devicesAtom, []);
    }, [atoms]);
    const send = useCallback(async (endpoint, data) => {
        if (!["/get/data/speech_server_state", "/get/data/speech_server_devices"].includes(endpoint)) setError(null);
        if (["/run/start_speech_server", "/run/stop_speech_server"].includes(endpoint)) {
            const generation = atoms.get(stateAtom)[data.profile]?.generation ?? -1;
            atoms.set(pendingAtom, { ...atoms.get(pendingAtom), [data.profile]: { generation } });
        }
        const response = await asyncStdoutToPython(endpoint, data);
        if (response === false) updateError("backend_unavailable");
        return response;
    }, [atoms, setError, updateError]);
    return { settings, state, devices, pending, error, send, updateSettings, updateState, updateDevices, updateError, reset, backendStopped };
};
