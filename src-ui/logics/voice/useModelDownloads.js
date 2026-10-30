import { atom, useAtom, useStore } from "jotai";
import { useCallback, useRef } from "react";
import { useStdoutToPython } from "@useStdoutToPython";

const catalogAtom = atom(null), stateAtom = atom({ observation_id: "0", jobs: {} });
const errorAtom = atom(null), pendingAtom = atom(null);
const hardwareAtom = atom({ phase: 'unknown', devices: [], observation_id: '0' });

export const useModelDownloads = () => {
    const store = useStore();
    const [catalog, setCatalog] = useAtom(catalogAtom), [state] = useAtom(stateAtom);
    const [error, setError] = useAtom(errorAtom), [pending, setPending] = useAtom(pendingAtom);
    const [hardware] = useAtom(hardwareAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const transport = useRef(asyncStdoutToPython);
    transport.current = asyncStdoutToPython;
    const updateCatalog = useCallback(value => setCatalog(value), [setCatalog]);
    const updateHardware = useCallback(value => {
        if (!/^\d+$/.test(value?.observation_id) || !Array.isArray(value.devices) ||
            BigInt(value.observation_id) <= BigInt(store.get(hardwareAtom).observation_id)) return;
        store.set(hardwareAtom, value);
    }, [store]);
    const updateState = useCallback(value => {
        if (!/^\d+$/.test(value?.observation_id) || !value.jobs ||
            BigInt(value.observation_id) <= BigInt(store.get(stateAtom).observation_id)) return false;
        store.set(stateAtom, value);
        return true;
    }, [store]);
    const acknowledge = useCallback(value => {
        // A poll can overtake the command response; it must not roll back state.
        updateState(value);
        setPending(null);
    }, [updateState, setPending]);
    const updateError = useCallback(value => { setError(value); setPending(null); }, [setError, setPending]);
    const reset = useCallback(() => {
        store.set(catalogAtom, null); store.set(stateAtom, { observation_id: "0", jobs: {} });
        store.set(errorAtom, null); store.set(pendingAtom, null);
        store.set(hardwareAtom, { phase: 'unknown', devices: [], observation_id: '0' });
    }, [store]);
    const send = useCallback(async (endpoint, data) => {
        const isHardware = endpoint.includes('model_download_hardware');
        if (endpoint.startsWith("/run/") && !isHardware) { setError(null); setPending({ endpoint, id: data.id }); }
        if (isHardware && endpoint.startsWith('/run/')) store.set(hardwareAtom, { ...store.get(hardwareAtom), phase: 'probing' });
        if (!await transport.current(endpoint, data)) {
            if (isHardware) store.set(hardwareAtom, { ...store.get(hardwareAtom), phase: 'failed', error_code: 'backend_unavailable' });
            else updateError("backend_unavailable");
        }
    }, [store, setPending, setError, updateError]);
    const ensureHardware = useCallback(() => {
        if (store.get(hardwareAtom).phase === 'unknown') send('/run/refresh_model_download_hardware', {});
    }, [store, send]);
    return { catalog, state, hardware, error, pending, send, ensureHardware, updateHardware, updateCatalog, updateState, acknowledge, updateError, reset };
};
