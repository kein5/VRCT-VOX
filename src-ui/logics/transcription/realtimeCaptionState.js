// Pure caption state. Receipt time is enforced by Python, identity/order here.
const sources = ["mic", "speaker"];
const states = ["partial", "final", "translated", "discarded"];
const idFor = p => `realtime:${p.source}:${p.namespace}:${p.item_id}`;
const retire = (retired, id) => [...retired.filter(value => value !== id), id].slice(-256);
const live = (p, active) => {
    const owner = active[p.source];
    return owner?.requested && owner.generation === p.generation && owner.namespace === p.namespace;
};

export const mergeRealtimeState = (current, incoming) => {
    const result = { ...current };
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
            result[source] = { ...next, namespace: next.namespace ??
                (next.generation === previous?.generation ? previous.namespace : null) };
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
        !Number.isSafeInteger(p.generation) || p.generation < 0 ||
        typeof p.text !== "string" || !live(p, activeNamespaces)) return current;
    const id = idFor(p), index = current.rows.findIndex(row => row.id === id);
    const previous = current.rows[index];
    if (current.retired.includes(id)) return current;
    if (previous && (p.revision <= previous.realtime.revision ||
        previous.realtime.state === "translated" ||
        (previous.realtime.state === "final" && p.state !== "translated"))) return current;
    if (p.state === "discarded" || !p.text.trim()) {
        return { rows: current.rows.filter(row => row.id !== id), retired: retire(current.retired, id) };
    }
    const row = {
        id, created_at: previous?.created_at ?? new Date().toLocaleTimeString("ja-JP", { hour12: false, hour: "2-digit", minute: "2-digit" }),
        category: p.source === "mic" ? "sent" : "received", status: p.state === "partial" ? "pending" : "ok",
        source: `realtime_${p.source}`,
        realtime: { source: p.source, namespace: p.namespace, generation: p.generation,
            item_id: p.item_id, revision: p.revision, state: p.state },
        messages: { original: p.original ?? { message: p.text, transliteration: [] }, translations: p.translations ?? [] },
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
    return { rows, retired };
};
