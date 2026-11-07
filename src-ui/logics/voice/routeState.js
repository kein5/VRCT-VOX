import { sameSnapshot, sameValue } from "../common/polledState.js";

// Windows has no managed virtual microphone; voice goes to the chosen output device.
export const usesOutputDevice = directState => directState?.output_route === "device";
export const directRouteReady = (settings, directState) =>
    usesOutputDevice(directState) ? !!settings?.output_device : settings?.routing === "managed";

// Call acceptObservation before reducing: the rendered ID may lag equal polls.
export const newerRoute = (previous, incoming) => {
    if (!incoming || typeof incoming.observation_id !== "string" || !/^\d+$/.test(incoming.observation_id)) return previous;
    if (previous.observation_id && BigInt(incoming.observation_id) <= BigInt(previous.observation_id)) return previous;
    return sameSnapshot(previous, incoming) ? previous : incoming;
};

// Each poll decodes a new `settings` object. Keep the previous one when nothing in
// it changed, so the forms built from it (direct voice, RVC) do not redo their
// draft and render again every second, also while settings are closed.
export const newerDirectState = (previous, incoming) => {
    const next = newerRoute(previous, incoming);
    if (next === previous || !previous.settings || !next.settings) return next;
    return sameValue(previous.settings, next.settings) ? { ...next, settings: previous.settings } : next;
};
