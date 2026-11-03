// Commands and polling share this reducer: delayed responses cannot assert stale mute.
export const newerRoute = (previous, incoming) => {
    if (!incoming || typeof incoming.observation_id !== "string" || !/^\d+$/.test(incoming.observation_id)) return previous;
    if (previous.observation_id && BigInt(incoming.observation_id) <= BigInt(previous.observation_id)) return previous;
    return incoming;
};

// Each poll decodes a new `settings` object. Keep the previous one when nothing in
// it changed, so the forms built from it (direct voice, RVC) do not redo their
// draft and render again every second, also while settings are closed.
export const newerDirectState = (previous, incoming) => {
    const next = newerRoute(previous, incoming);
    if (next === previous || !previous.settings || !next.settings) return next;
    return JSON.stringify(previous.settings) === JSON.stringify(next.settings) ? { ...next, settings: previous.settings } : next;
};
