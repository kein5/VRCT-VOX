import { sameValue } from "../common/polledState.js";
import { speakerLabels } from "../common/speakerLabels.js";

// Pure caption state. Receipt time is enforced by Python, identity/order here.
const sources = ["mic", "speaker"];
const states = ["partial", "final", "translated", "discarded", "outcome"];
const outcomes = { delivered: "ok", not_delivered: "not_sent", failed: "failed" };
const idFor = p => `realtime:${p.source}:${p.generation}:${p.namespace}:${p.item_id}`;
const retire = (retired, id) => [...retired.filter(value => value !== id), id].slice(-256);
const live = (p, active) => {
    const owner = active[p.source];
    return owner?.requested && owner.generation === p.generation && owner.namespace === p.namespace;
};

export const mergeRealtimeState = (current, incoming) => {
    let result = current;
    for (const source of sources) {
        const next = incoming?.[source], previous = current[source];
        if (!Number.isSafeInteger(next?.generation) || next.generation < 0) continue;
        if (next.generation === previous?.generation) {
            if (["stopping", "closed", "failed"].includes(previous.state) && next.requested) continue;
            if (previous.state === "ready" && next.state === "starting") continue;
        }
        if (!previous || next.generation >= previous.generation) {
            // A delayed starting snapshot may omit a namespace learned from a
            // newer caption in the same generation; do not forget its identity.
            const row = { ...next, namespace: next.namespace ??
                (next.generation === previous?.generation ? previous.namespace : null) };
            if (!sameValue(previous, row)) {
                if (result === current) result = { ...current };
                result[source] = row;
            }
        }
    }
    return result;
};

export const applyRealtimeCaption = (current, payload, activeNamespaces) => {
    const p = payload;
    if (!p || !sources.includes(p.source) || !states.includes(p.state) ||
        typeof p.namespace !== "string" || !p.namespace || p.namespace.length > 128 ||
        typeof p.item_id !== "string" || !p.item_id || p.item_id.length > 256 ||
        !Number.isSafeInteger(p.revision) || p.revision < 1 ||
        !Number.isSafeInteger(p.generation) || p.generation < 0) return current;
    const id = idFor(p), index = current.rows.findIndex(row => row.id === id);
    const previous = current.rows[index];
    if (current.retired.includes(id)) return current;
    // Outcomes settle only an existing recognized row, including an old
    // generation after stop. They cannot recreate a pruned/unknown item.
    if (p.state === "outcome") {
        if (!Object.hasOwn(outcomes, p.outcome) || !previous || previous.realtime.outcome ||
            !["final", "translated"].includes(previous.realtime.state) ||
            p.revision <= previous.realtime.revision) return current;
        const rows = [...current.rows];
        rows[index] = { ...previous, status: outcomes[p.outcome], realtime: {
            ...previous.realtime, revision: p.revision, outcome: p.outcome, reason: p.reason,
        } };
        return { ...current, rows };
    }
    if (typeof p.text !== "string" || !live(p, activeNamespaces)) return current;
    if (previous?.realtime.outcome) return current;
    if (previous && (p.revision <= previous.realtime.revision ||
        previous.realtime.state === "translated" ||
        (previous.realtime.state === "final" && p.state !== "translated"))) return current;
    if (p.state === "discarded" || !p.text.trim()) {
        return { rows: current.rows.filter(row => row.id !== id), retired: retire(current.retired, id) };
    }
    // Only a completed utterance names its speakers; its translated row keeps them.
    const named = p.source === "speaker" ? speakerLabels(p.speakers) : [];
    const speakers = named.length ? named : previous?.speakers ?? [];
    const row = {
        id, created_at: previous?.created_at ?? new Date().toLocaleTimeString("ja-JP", { hour12: false, hour: "2-digit", minute: "2-digit" }),
        category: p.source === "mic" ? "sent" : "received", status: "pending",
        source: `realtime_${p.source}`,
        realtime: { source: p.source, namespace: p.namespace, generation: p.generation,
            item_id: p.item_id, revision: p.revision, state: p.state },
        messages: { original: p.original ?? { message: p.text, transliteration: [] }, translations: p.translations ?? [] },
        ...(speakers.length ? { speakers } : {}),
    };
    const rows = [...current.rows];
    if (index < 0) rows.push(row);
    else rows[index] = row;
    return { ...current, rows };
};

export const pruneRealtimeCaptions = (current, activeNamespaces) => {
    let retired = current.retired;
    const rows = current.rows.filter(row => {
        if (row.realtime?.state !== "partial" || live(row.realtime, activeNamespaces)) return true;
        retired = retire(retired, row.id);
        return false;
    });
    return rows.length === current.rows.length ? current : { rows, retired };
};
