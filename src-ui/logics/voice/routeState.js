// Commands and polling share this reducer: delayed responses cannot assert stale mute.
export const newerRoute = (previous, incoming) => {
    if (!incoming || typeof incoming.observation_id !== "string" || !/^\d+$/.test(incoming.observation_id)) return previous;
    if (previous.observation_id && BigInt(incoming.observation_id) <= BigInt(previous.observation_id)) return previous;
    return incoming;
};
