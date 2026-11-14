// Words for the flow panel and its overlays. The main window words everything; the desktop
// overlay window only draws the strings it is handed. Durations are always whole ms.
import { formatMs, latestTraces, outputArrivals, stageSegments, timelineScale, traceTotal } from "./ioFlow.js";

const ENGINE_NAMES = { rvc: "RVC", "seed-vc": "Seed-VC" };

// What an output of the route map does now, or why it is not used.
export const outputDetail = (row, t, names) => {
    if (!row.on) return t(`io_flow.reason.${row.reason}`);
    if (row.id === "chatbox") return t(`io_flow.content.${row.content}`);
    if (row.id === "speech") {
        return [
            row.content ? t(`io_flow.chat_speech.${row.content}`) : null,
            row.language ? t("io_flow.speech_language", { language: names.language(row.language) }) : null,
            t(`io_flow.speech_path.${row.path}`),
        ].filter(Boolean).join(" · ");
    }
    if (row.id === "live_voice") {
        const carried = row.carried === "converted"
            ? (ENGINE_NAMES[row.engine] ? t("io_flow.live.converted", { engine: ENGINE_NAMES[row.engine] }) : t("io_flow.live.converted_unknown"))
            : t(`io_flow.live.${row.carried}`);
        return row.during_speech ? `${carried} · ${t(`io_flow.during_speech.${row.during_speech}`)}` : carried;
    }
    return t("io_flow.used");
};

// The outputs not in use, one group per reason: "VR log, Clipboard" and why.
export const offGroups = (outputs, t) => {
    const groups = new Map();
    for (const row of outputs ?? []) {
        if (row.on) continue;
        if (!groups.has(row.reason)) groups.set(row.reason, []);
        groups.get(row.reason).push(t(`io_flow.output.${row.id}`));
    }
    return [...groups].map(([reason, names]) => ({ reason, outputs: names.join(t("io_flow.list_separator")),
        text: t(`io_flow.reason.${reason}`) }));
};

// The latest trace's time for an output of the route map, worded; null when it has none.
export const outputTime = (row, trace, t) => {
    if (!trace) return null;
    const state = trace.outputs?.[row.id === "speech" ? "speech" : row.id]?.state;
    const arrival = outputArrivals(trace).find(entry => entry.kind === row.id);
    if (arrival) return formatMs(arrival.end ?? arrival.at);
    if (["queued", "not_spoken", "off", "superseded", "failed"].includes(state)) return t(`io_flow.state.${state}`);
    return null;
};

// The rows of a timeline: the stages one after another, then each output's arrival.
export const timelineRows = (trace, t) => {
    const rows = stageSegments(trace).map(segment => ({
        kind: "stage", stage: segment.kind, label: t(`io_flow.stage.${segment.kind}`), value: formatMs(segment.ms),
        start: segment.start, end: segment.start + segment.ms, off: false,
    }));
    for (const arrival of outputArrivals(trace)) {
        rows.push({ kind: arrival.kind, label: t(`io_flow.output_short.${arrival.kind}`), value: formatMs(arrival.at),
            start: 0, end: arrival.at, off: false });
        if (arrival.conversion !== null && arrival.conversion !== undefined) {
            rows.push({ kind: "conversion", label: t("io_flow.conversion_guide"), value: formatMs(arrival.conversion),
                start: arrival.at, end: arrival.end, off: false });
        }
    }
    // Outputs the message did not reach say so, without a bar.
    for (const name of ["chatbox", "speech"]) {
        const state = trace?.outputs?.[name]?.state;
        if (["off", "superseded", "failed", "not_spoken", "queued"].includes(state)) {
            rows.push({ kind: name, label: t(`io_flow.output_short.${name}`), value: t(`io_flow.state.${state}`), start: 0, end: 0, off: true });
        }
    }
    return rows;
};

// The desktop strip: the newest `count` inputs, worded and ready to draw.
export const stripItems = (traces, count, t) => latestTraces(traces, count).map(trace => {
    const total = traceTotal(trace);
    return {
        id: trace.id, input: trace.input,
        label: t(`io_flow.${trace.input}`),
        text: (trace.translation ? `${trace.text} → ${trace.translation}` : trace.text).slice(0, 200),
        scale: Math.min(timelineScale(total ?? 0), 600000),
        rows: timelineRows(trace, t).filter(row => row.kind !== "stage" || ["recognition", "translate"].includes(row.stage))
            .slice(0, 8).map(({ kind, label, value, start, end, off }) => ({
            kind, label: label.slice(0, 120), value: value.slice(0, 120),
            start: Math.min(start, 600000), end: Math.min(end, 600000), off })),
    };
}).map(item => ({ ...item, rows: item.rows.map(row => ({ ...row, end: Math.min(row.end, item.scale), start: Math.min(row.start, item.scale) })) }));

// The live reading under the strip: the conversion's recent round trip, while it runs.
export const flowNote = (flow, t) => Number.isInteger(flow?.conversion_round_trip_ms)
    ? t("io_flow.conversion_live", { ms: flow.conversion_round_trip_ms }) : "";
