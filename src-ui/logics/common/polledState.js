// IPC snapshots contain JSON values. Object key order is not meaningful.
export const sameValue = (left, right) => {
    if (Object.is(left, right)) return true;
    if (!left || !right || typeof left !== "object" || typeof right !== "object" ||
        Array.isArray(left) !== Array.isArray(right)) return false;
    const keys = Object.keys(left);
    return keys.length === Object.keys(right).length &&
        keys.every(key => Object.hasOwn(right, key) && sameValue(left[key], right[key]));
};

export const sameSnapshot = (left, right) => {
    const keys = Object.keys(left).filter(key => key !== "observation_id");
    return keys.length === Object.keys(right).filter(key => key !== "observation_id").length &&
        keys.every(key => Object.hasOwn(right, key) && sameValue(left[key], right[key]));
};

// Shared by hook instances, isolated by Jotai store and atom. An equal snapshot
// still advances this cursor without publishing an atom update.
const observations = new WeakMap();
export const acceptObservation = (store, target, incoming) => {
    const id = incoming?.observation_id;
    if (typeof id !== "string" || !/^\d+$/.test(id)) return false;
    let cursors = observations.get(store);
    if (!cursors) observations.set(store, cursors = new Map());
    const latest = cursors.get(target) ?? store.get(target).observation_id;
    if (latest != null && BigInt(id) <= BigInt(latest)) return false;
    cursors.set(target, id);
    return true;
};

export const resetObservations = (store, targets) => {
    const cursors = observations.get(store);
    for (const target of targets) cursors?.delete(target);
};
