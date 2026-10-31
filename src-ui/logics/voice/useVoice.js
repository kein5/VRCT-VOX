import { atom, useAtom, useStore } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";
import { newerRoute } from "./routeState";

const settingsAtom = atom(null), statusAtom = atom({}), routeAtom = atom({});
const devicesAtom = atom({ devices: [], error: null }), errorAtom = atom(null);
const directStateAtom = atom({}), directSourcesAtom = atom({ sources: [], error: null }), directErrorAtom = atom(null);
const selectedSourceAtom = atom(""), preferredSourceAtom = atom("");
const modelOptionsAtom = atom({});
let optionsSequence = 0;
const ttsPendingAtom = atom(null), directPendingAtom = atom(null), ttsErrorAtom = atom(null);
// Keep the last producer through stopping/health failure, where backend mode is already off.
const directOwnerAtom = atom(null);
const directDraftBlockedAtom = atom(false);
const inputOwner = (mode, engine) => mode === "converted" ? engine || "seed-vc" : "passthrough";
// Keep the complete backend identity. Refresh never rebinds a selected name.
export const sourceKey = id => JSON.stringify([id.cookie, id.serial, id.name, id.media_class]);

export const useVoice = () => {
    const atoms = useStore();
    const [modelOptions] = useAtom(modelOptionsAtom);
    const updateModelOptions = useCallback(value => {
        const previous = atoms.get(modelOptionsAtom);
        if (!value || !["japanese", "multilingual"].includes(value.role) || previous[value.role]?.request_id !== value.request_id) return;
        atoms.set(modelOptionsAtom, { ...previous, [value.role]: value });
    }, [atoms]);
    const [settings, setSettings] = useAtom(settingsAtom);
    const [status] = useAtom(statusAtom);
    const [route, setRoute] = useAtom(routeAtom);
    const [devices, updateDevices] = useAtom(devicesAtom);
    const [error, updateError] = useAtom(errorAtom);
    const [directState] = useAtom(directStateAtom);
    const [directOwner] = useAtom(directOwnerAtom);
    const [directDraftBlocked, setDirectDraftBlocked] = useAtom(directDraftBlockedAtom);
    const [directSources] = useAtom(directSourcesAtom);
    const [directError] = useAtom(directErrorAtom);
    const [selectedSource, setSelectedSource] = useAtom(selectedSourceAtom);
    const [ttsPending] = useAtom(ttsPendingAtom), [directPending] = useAtom(directPendingAtom), [ttsError] = useAtom(ttsErrorAtom);
    const updateTtsError = useCallback((value, endpoint) => {
        atoms.set(ttsErrorAtom, value);
        if (value && endpoint === "/run/enable_tts" && atoms.get(ttsPendingAtom)?.intent)
            atoms.set(ttsPendingAtom, null);
    }, [atoms]);
    const updateDirectError = useCallback((value, endpoint) => {
        atoms.set(directErrorAtom, value);
        if (value && endpoint === "/run/start_direct_voice" && atoms.get(directPendingAtom)?.intent)
            atoms.set(directPendingAtom, null);
    }, [atoms]);
    // The Device page Mic choice (backend `preferred`) is the default input. Follow it
    // until another input is picked here; never retarget an input that is running.
    const updateDirectSources = useCallback(value => {
        atoms.set(directSourcesAtom, value);
        const next = value?.preferred ? sourceKey(value.preferred) : "", state = atoms.get(directStateAtom);
        if (!next || atoms.get(directPendingAtom) || state.requested || state.pending || state.stopping) return;
        const selected = atoms.get(selectedSourceAtom);
        if (selected === "" || selected === atoms.get(preferredSourceAtom)) atoms.set(selectedSourceAtom, next);
        atoms.set(preferredSourceAtom, next);
    }, [atoms]);
    const updateSettings = useCallback(value => { setSettings(value); updateError(null); }, [setSettings, updateError]);
    const updateStatus = useCallback(value => {
        const previous = atoms.get(statusAtom), next = newerRoute(previous, value);
        if (next === previous || (previous.tts_generation != null && next.tts_generation < previous.tts_generation)) return;
        atoms.set(statusAtom, next);
        const waiting = atoms.get(ttsPendingAtom);
        if (waiting && next.tts_generation > waiting.generation && next.tts_enabled === waiting.intent) {
            atoms.set(ttsPendingAtom, null);
            if (["voice_request_unconfirmed", "backend_unavailable"].includes(atoms.get(ttsErrorAtom))) atoms.set(ttsErrorAtom, null);
        }
    }, [atoms]);
    const updateRoute = useCallback(value => setRoute(previous => newerRoute(previous, value)), [setRoute]);
    const updateDirectState = useCallback(value => {
        const previous = atoms.get(directStateAtom), next = newerRoute(previous, value);
        if (next === previous) return;
        atoms.set(directStateAtom, next);
        if (next.mode && next.mode !== "off")
            atoms.set(directOwnerAtom, inputOwner(next.mode, next.settings?.engine));
        const waiting = atoms.get(directPendingAtom);
        if (waiting && next.generation > waiting.generation &&
            ((!!next.requested === waiting.intent && (waiting.intent || (!next.pending && !next.stopping))) ||
             (waiting.intent && next.error))) {
            atoms.set(directPendingAtom, null);
            if (["voice_request_unconfirmed", "backend_unavailable"].includes(atoms.get(directErrorAtom))) atoms.set(directErrorAtom, null);
        }
    }, [atoms]);
    const { asyncStdoutToPython } = useStdoutToPython();
    const send = useCallback(async (endpoint, data) => {
        if (endpoint === "/get/data/tts_model_options") {
            data = { ...data, request_id: `ui-${Date.now()}-${++optionsSequence}` };
            atoms.set(modelOptionsAtom, { ...atoms.get(modelOptionsAtom), [data.role]: { request_id: data.request_id, options: null } });
        }
        const ttsCommand = ["/run/enable_tts", "/run/disable_tts"].includes(endpoint);
        const directCommand = ["/run/start_direct_voice", "/run/stop_direct_voice"].includes(endpoint);
        const direct = endpoint.includes("direct_voice");
        const report = ttsCommand ? updateTtsError : direct ? updateDirectError : updateError;
        if (ttsCommand || directCommand) {
            report(null);
            const target = ttsCommand ? ttsPendingAtom : directPendingAtom;
            const state = atoms.get(ttsCommand ? statusAtom : directStateAtom);
            const request = { intent: endpoint === "/run/enable_tts" || endpoint === "/run/start_direct_voice",
                generation: (ttsCommand ? state.tts_generation : state.generation) ?? -1 };
            if (directCommand) {
                request.owner = request.intent ? inputOwner(data?.mode, data?.options?.engine) : atoms.get(directOwnerAtom);
                atoms.set(directOwnerAtom, request.owner);
            }
            atoms.set(target, request);
            setTimeout(() => { if (atoms.get(target) === request) report("voice_request_unconfirmed"); }, 5000);
        } else if (endpoint.startsWith("/set/") || endpoint === "/run/mute_voice" || endpoint === "/run/resume_voice") report(null);
        const ok = await asyncStdoutToPython(endpoint, data);
        if (!ok) report("backend_unavailable");
        return ok;
    }, [atoms, updateError, updateTtsError, updateDirectError]);
    const reset = useCallback(() => {
        atoms.set(modelOptionsAtom, {});
        atoms.set(settingsAtom, null); atoms.set(statusAtom, {}); atoms.set(routeAtom, {}); atoms.set(directStateAtom, {});
        atoms.set(selectedSourceAtom, ""); atoms.set(preferredSourceAtom, ""); atoms.set(directSourcesAtom, { sources: [], error: null });
        atoms.set(directOwnerAtom, null); atoms.set(directDraftBlockedAtom, false);
        for (const target of [errorAtom, directErrorAtom, ttsErrorAtom, ttsPendingAtom, directPendingAtom]) atoms.set(target, null);
    }, [atoms]);
    return { settings, status, route, devices, error, send, reset, modelOptions, updateModelOptions, selectedSource, setSelectedSource,
        ttsPending, directPending, ttsError, updateTtsError, updateStatus, updateRoute, updateDevices, updateError,
        directState, directOwner, directDraftBlocked, setDirectDraftBlocked,
        directSources, directError, updateDirectState, updateDirectSources, updateDirectError, updateSettings };
};
