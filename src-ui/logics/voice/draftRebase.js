const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const record = value => value !== null && typeof value === "object" && !Array.isArray(value);

// Moves unsaved edits onto a newer saved value, e.g. after a model path was
// applied. Fields the user did not edit follow the backend; edited fields keep
// the user's value. Key order follows `saved` so dirty checks stay stable.
export const rebaseDraft = (base, draft, saved) => {
    if (same(draft, base)) return saved;
    if (![base, draft, saved].every(record)) return draft;
    return Object.fromEntries(Object.keys(saved).map(key => [key, rebaseDraft(base[key], draft[key], saved[key])]));
};
