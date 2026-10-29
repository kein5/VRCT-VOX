import { atom, useAtom, useStore } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";

const settingsAtom = atom(null), stateAtom = atom({}), pendingAtom = atom({}), errorAtom = atom(null);
const phases = { stopped: 0, preparing: 1, ready: 2, stopping: 3, failed: 4 };
const profiles = ["japanese", "multilingual", "asr"];

export const useSpeechServers = () => {
    const atoms = useStore();
    const [settings, setSettings] = useAtom(settingsAtom);
    const [state] = useAtom(stateAtom);
    const [pending] = useAtom(pendingAtom);
    const [error, setError] = useAtom(errorAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const updateError = useCallback(value => {
        setError(value);
        if (value) atoms.set(pendingAtom, {});
    }, [atoms, setError]);
    const updateSettings = useCallback(value => { setSettings(value); setError(null); }, [setSettings, setError]);
    const updateState = useCallback(value => {
        const next = { ...atoms.get(stateAtom) }, waiting = { ...atoms.get(pendingAtom) };
        for (const name of profiles) {
            const row = value?.[name], previous = next[name];
            if (!Number.isSafeInteger(row?.generation) || row.generation < 0 || !(row.state in phases)) continue;
            if (previous && (row.generation < previous.generation ||
                (row.generation === previous.generation && phases[row.state] < phases[previous.state]))) continue;
            next[name] = row;
            if (waiting[name] && row.generation > waiting[name].generation) delete waiting[name];
        }
        atoms.set(stateAtom, next);
        atoms.set(pendingAtom, waiting);
    }, [atoms]);
    const reset = useCallback(() => {
        atoms.set(settingsAtom, null);
        atoms.set(stateAtom, {});
        atoms.set(pendingAtom, {});
        atoms.set(errorAtom, null);
    }, [atoms]);
    const send = useCallback(async (endpoint, data) => {
        if (endpoint !== "/get/data/speech_server_state") setError(null);
        if (["/run/start_speech_server", "/run/stop_speech_server"].includes(endpoint)) {
            const generation = atoms.get(stateAtom)[data.profile]?.generation ?? -1;
            atoms.set(pendingAtom, { ...atoms.get(pendingAtom), [data.profile]: { generation } });
        }
        if (!await asyncStdoutToPython(endpoint, data)) updateError("backend_unavailable");
    }, [atoms, setError, updateError]);
    return { settings, state, pending, error, send, updateSettings, updateState, updateError, reset };
};
