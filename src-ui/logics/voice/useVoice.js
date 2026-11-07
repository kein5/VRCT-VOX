import { atom, useAtom, useStore } from "jotai";
import { useCallback } from "react";
import { useStdoutToPython } from "@useStdoutToPython";
import { pendingAfterVoiceFailure, stoppedVoiceStatus, stoppedDirectState } from "./pendingVoiceRequest.js";
import { newerRoute, newerDirectState } from "./routeState";
import { acceptObservation, resetObservations } from "../common/polledState.js";

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
// Windows has no managed virtual microphone; voice goes to the chosen output device.
export const usesOutputDevice = directState => directState?.output_route === "device";
export const directRouteReady = (settings, directState) =>
    usesOutputDevice(directState) ? !!settings?.output_device : settings?.routing === "managed";

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
    const [route] = useAtom(routeAtom);
    const [devices, updateDevices] = useAtom(devicesAtom);
    const [error, updateError] = useAtom(errorAtom);
    const [directState] = useAtom(directStateAtom);
    const [directOwner] = useAtom(directOwnerAtom);
    const [directDraftBlocked, setDirectDraftBlocked] = useAtom(directDraftBlockedAtom);
    const [directSources] = useAtom(directSourcesAtom);
    const [directError] = useAtom(directErrorAtom);
    const [selectedSource, setSelectedSource] = useAtom(selectedSourceAtom);
    const [ttsPending] = useAtom(ttsPendingAtom), [directPending] = useAtom(directPendingAtom), [ttsError] = useAtom(ttsErrorAtom);
    const updateTtsError = useCallback((value, endpoint, status) => {
        // OFF while a bundled server was starting cancels that ON; nothing to report.
        if (value === "tts_enable_cancelled") return;
        atoms.set(ttsErrorAtom, value);
        if ([404, 423, 500].includes(status))
            atoms.set(ttsPendingAtom, pending => pendingAfterVoiceFailure(pending, endpoint));
        if (value && endpoint === "/run/enable_tts" && atoms.get(ttsPendingAtom)?.intent)
            atoms.set(ttsPendingAtom, null);
    }, [atoms]);
    const updateDirectError = useCallback((value, endpoint, status) => {
        atoms.set(directErrorAtom, value);
        if ([404, 423, 500].includes(status))
            atoms.set(directPendingAtom, pending => pendingAfterVoiceFailure(pending, endpoint));
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
        const previous = atoms.get(statusAtom);
        if ((previous.tts_generation != null && value?.tts_generation < previous.tts_generation) ||
            !acceptObservation(atoms, statusAtom, value)) return;
        atoms.set(statusAtom, newerRoute(previous, value));
        const waiting = atoms.get(ttsPendingAtom);
        if (waiting && value.tts_generation > waiting.generation && value.tts_enabled === waiting.intent) {
            atoms.set(ttsPendingAtom, null);
            if (["voice_request_unconfirmed", "backend_unavailable"].includes(atoms.get(ttsErrorAtom))) atoms.set(ttsErrorAtom, null);
        }
    }, [atoms]);
    const updateRoute = useCallback(value => {
        if (acceptObservation(atoms, routeAtom, value)) atoms.set(routeAtom, previous => newerRoute(previous, value));
    }, [atoms]);
    const updateDirectState = useCallback(value => {
        if (!acceptObservation(atoms, directStateAtom, value)) return;
        const previous = atoms.get(directStateAtom), next = newerDirectState(previous, value);
        atoms.set(directStateAtom, next);
        if (value.mode && value.mode !== "off")
            atoms.set(directOwnerAtom, inputOwner(value.mode, value.settings?.engine));
        const waiting = atoms.get(directPendingAtom);
        if (waiting && value.generation > waiting.generation &&
            ((!!value.requested === waiting.intent && (waiting.intent || (!value.pending && !value.stopping))) ||
             (waiting.intent && value.error))) {
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
        let pendingTarget, pendingRequest;
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
            pendingTarget = target;
            pendingRequest = request;
            atoms.set(target, request);
            const confirm = () => {
                if (atoms.get(target) !== request) return;
                // ON may be loading a bundled server's model, which takes longer than 5 s.
                if (ttsCommand && request.intent && atoms.get(statusAtom).tts_server_starting === true)
                    return setTimeout(confirm, 1000);
                report("voice_request_unconfirmed");
            };
            setTimeout(confirm, 5000);
        } else if (endpoint.startsWith("/set/") || endpoint === "/run/mute_voice" || endpoint === "/run/resume_voice") report(null);
        const ok = await asyncStdoutToPython(endpoint, data);
        if (ok === false) {
            // A delayed transport failure must not clear a newer command's owner.
            if (pendingTarget && atoms.get(pendingTarget) === pendingRequest) atoms.set(pendingTarget, null);
            report("backend_unavailable");
        }
        return ok;
    }, [atoms, updateError, updateTtsError, updateDirectError]);
    const backendStopped = useCallback(() => {
        atoms.set(ttsPendingAtom, null); atoms.set(directPendingAtom, null);
        atoms.set(statusAtom, stoppedVoiceStatus);
        atoms.set(directStateAtom, stoppedDirectState);
        atoms.set(routeAtom, value => ({ ...value, pending: false }));
        for (const target of [errorAtom, directErrorAtom, ttsErrorAtom]) atoms.set(target, "backend_unavailable");
    }, [atoms]);
    const reset = useCallback(() => {
        resetObservations(atoms, [statusAtom, routeAtom, directStateAtom]);
        atoms.set(modelOptionsAtom, {});
        atoms.set(settingsAtom, null); atoms.set(statusAtom, {}); atoms.set(routeAtom, {}); atoms.set(directStateAtom, {});
        atoms.set(selectedSourceAtom, ""); atoms.set(preferredSourceAtom, ""); atoms.set(directSourcesAtom, { sources: [], error: null });
        atoms.set(directOwnerAtom, null); atoms.set(directDraftBlockedAtom, false);
        for (const target of [errorAtom, directErrorAtom, ttsErrorAtom, ttsPendingAtom, directPendingAtom]) atoms.set(target, null);
    }, [atoms]);
    return { settings, status, route, devices, error, send, reset, backendStopped, modelOptions, updateModelOptions, selectedSource, setSelectedSource,
        ttsPending, directPending, ttsError, updateTtsError, updateStatus, updateRoute, updateDevices, updateError,
        directState, directOwner, directDraftBlocked, setDirectDraftBlocked,
        directSources, directError, updateDirectState, updateDirectSources, updateDirectError, updateSettings };
};
