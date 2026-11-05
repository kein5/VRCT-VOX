import { atom, useAtom, useStore } from "jotai";
import { useCallback } from "react";
import { Atom_MessageLogs } from "@store";
import { useStdoutToPython } from "@useStdoutToPython";
import { mergeRealtimeState, pruneRealtimeCaptions } from "./realtimeCaptionState";

export const realtimeStateAtom = atom({});
export const realtimeRetiredAtom = atom([]);
const settingsAtom = atom(null);
const endpointsAtom = atom({});
const modelsAtom = atom({ models: [] });
const errorAtom = atom(null);

export const useRealtimeASR = () => {
    const [settings, setSettings] = useAtom(settingsAtom);
    const [state] = useAtom(realtimeStateAtom);
    const [endpoints] = useAtom(endpointsAtom);
    const [models, updateModels] = useAtom(modelsAtom);
    const [error, updateError] = useAtom(errorAtom);
    const atoms = useStore();
    const { asyncStdoutToPython } = useStdoutToPython();
    const updateState = useCallback(value => {
        const next = mergeRealtimeState(atoms.get(realtimeStateAtom), value);
        atoms.set(realtimeStateAtom, next);
        const logs = atoms.get(Atom_MessageLogs);
        const pruned = pruneRealtimeCaptions({ rows: logs.data, retired: atoms.get(realtimeRetiredAtom) }, next);
        if (pruned.rows !== logs.data) atoms.set(Atom_MessageLogs, { ...logs, data: pruned.rows });
        atoms.set(realtimeRetiredAtom, pruned.retired);
    }, [atoms]);
    const backendStopped = useCallback(() => {
        updateError("backend_unavailable");
        updateState(Object.fromEntries(Object.entries(atoms.get(realtimeStateAtom)).map(([source, row]) =>
            [source, { ...row, requested: false, state: "failed", error_code: "backend_unavailable" }])));
        // A lost sidecar cannot confirm delivery. Keep recognized text, and
        // preserve outcomes already received before the connection closed.
        const logs = atoms.get(Atom_MessageLogs);
        const rows = logs.data.map(row => row.realtime && !row.realtime.outcome
            ? { ...row, status: "failed", realtime: { ...row.realtime, outcome: "failed", reason: "backend_unavailable" } }
            : row);
        if (rows.some((row, index) => row !== logs.data[index])) atoms.set(Atom_MessageLogs, { ...logs, data: rows });
    }, [atoms, updateError, updateState]);
    const reset = useCallback(() => {
        atoms.set(realtimeStateAtom, {});
        atoms.set(realtimeRetiredAtom, []);
        atoms.set(settingsAtom, null);
        atoms.set(endpointsAtom, {});
        atoms.set(modelsAtom, { models: [] });
        atoms.set(errorAtom, null);
        const logs = atoms.get(Atom_MessageLogs);
        atoms.set(Atom_MessageLogs, { ...logs, data: logs.data.filter(row => row.realtime?.state !== "partial") });
    }, [atoms]);
    const updateSettings = useCallback(value => {
        const previous = atoms.get(settingsAtom);
        if (previous) {
            const active = atoms.get(realtimeStateAtom), invalidated = {};
            const shared = previous.server !== value.server || previous.base_url !== value.base_url || previous.model !== value.model;
            for (const source of ["mic", "speaker"]) {
                if (active[source] && (shared || JSON.stringify(previous[source]) !== JSON.stringify(value[source]))) {
                    invalidated[source] = { ...active[source], requested: false, state: "stopping" };
                }
            }
            updateState(invalidated);
        }
        setSettings(value);
        updateError(null);
    }, [atoms, setSettings, updateError, updateState]);
    const updateEndpoints = useCallback(value => {
        if (["mic", "speaker"].includes(value?.source)) {
            atoms.set(endpointsAtom, { ...atoms.get(endpointsAtom), [value.source]: value });
        }
    }, [atoms]);
    // Identity and ordering always read the atom store, including within one
    // response batch before React rerenders. Hook closures are not authority.
    const send = useCallback(async (endpoint, data) => {
        if (endpoint !== "/get/data/realtime_asr_state") updateError(null);
        const response = await asyncStdoutToPython(endpoint, data);
        if (response === false) updateError("backend_unavailable");
        return response;
    }, [updateError]);
    return { settings, state, endpoints, models, error, send, updateSettings,
        updateState, updateEndpoints, updateModels, updateError, reset, backendStopped };
};
