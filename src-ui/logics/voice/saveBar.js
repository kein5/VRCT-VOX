import { useSyncExternalStore } from "react";

// Settings forms with a draft register here so the config page top bar can
// show what changed and save or discard every open form in one place.
const entries = new Map();
const listeners = new Set();
let snapshot = [];

const publish = () => {
    snapshot = [...entries.values()];
    listeners.forEach(listener => listener());
};

export const setSaveBarEntry = (id, entry) => {
    if (entry) entries.set(id, entry);
    else entries.delete(id);
    publish();
};

const subscribe = listener => {
    listeners.add(listener);
    return () => listeners.delete(listener);
};

export const useSaveBarEntries = () => useSyncExternalStore(subscribe, () => snapshot);

const record = value => value !== null && typeof value === "object" && !Array.isArray(value);

// Paths of the leaves that differ, e.g. [["profiles", "asr", "model"]].
export const changedPaths = (saved, draft, path = []) => {
    if (JSON.stringify(saved) === JSON.stringify(draft)) return [];
    if (!record(saved) || !record(draft)) return [path];
    const keys = new Set([...Object.keys(saved), ...Object.keys(draft)]);
    return [...keys].flatMap(key => changedPaths(saved[key], draft[key], [...path, key]));
};
