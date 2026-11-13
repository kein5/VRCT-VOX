import { atom, useAtom, useStore } from "jotai";
import { useCallback, useRef } from "react";
import { useStdoutToPython } from "@useStdoutToPython";
import { acceptObservation, resetObservations, sameSnapshot } from "../common/polledState.js";

export const activeSetupPhases = ["queued", "tools", "python", "packages", "engine", "assets", "verifying", "cancelling"];
const emptyState = { observation_id: "0", jobs: {}, installed: {} };
const catalogAtom = atom(null), stateAtom = atom(emptyState), errorAtom = atom(null), pendingAtom = atom(false);

export const useVcRuntimes = () => {
    const store = useStore();
    const [catalog, setCatalog] = useAtom(catalogAtom), [state] = useAtom(stateAtom);
    const [error, setError] = useAtom(errorAtom), [pending, setPending] = useAtom(pendingAtom);
    const { asyncStdoutToPython } = useStdoutToPython();
    const transport = useRef(asyncStdoutToPython);
    transport.current = asyncStdoutToPython;
    const updateCatalog = useCallback(value => setCatalog(value), [setCatalog]);
    const updateState = useCallback(value => {
        if (!value?.jobs || !acceptObservation(store, stateAtom, value)) return;
        store.set(stateAtom, previous => sameSnapshot(previous, value) ? previous : value);
    }, [store]);
    const acknowledge = useCallback(value => { updateState(value); setPending(false); }, [updateState, setPending]);
    const updateError = useCallback(value => { setError(value); setPending(false); }, [setError, setPending]);
    const send = useCallback(async (endpoint, data) => {
        const command = endpoint.startsWith("/run/");
        if (command) {
            if (store.get(pendingAtom)) return;
            setError(null); setPending(true);
        }
        if (!await transport.current(endpoint, data) && command) updateError("backend_unavailable");
    }, [store, setError, setPending, updateError]);
    const reset = useCallback(() => {
        resetObservations(store, [stateAtom]);
        store.set(catalogAtom, null); store.set(stateAtom, emptyState);
        store.set(errorAtom, null); store.set(pendingAtom, false);
    }, [store]);
    const backendStopped = useCallback(() => {
        updateError("backend_unavailable");
        store.set(stateAtom, value => ({ ...value, jobs: Object.fromEntries(Object.entries(value.jobs).map(([id, job]) =>
            [id, activeSetupPhases.includes(job.phase) ? { ...job, phase: "failed", error_code: "backend_unavailable" } : job])) }));
    }, [store, updateError]);
    return { catalog, state, error, pending, send, updateCatalog, updateState, acknowledge, updateError, reset, backendStopped };
};
