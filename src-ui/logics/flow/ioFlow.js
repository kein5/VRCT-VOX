// The flow panel's data, shared by the main window, the desktop overlay and the VR window.
// - The route map comes from /get/data/io_flow: two lanes (the user's voice, typed chat),
//   each output on or off, and why when off.
// - Each of the user's own messages arrives as a trace from /run/io_trace: the ms from a
//   named origin to each stage and output. Speech that starts later sends the same id again.
// Every duration here is in ms.

export const TRACE_KEEP = 20;
export const INPUTS = ["voice", "chat"];
// Stages before any output, in the order they happen.
export const STAGES = ["recognition", "wait", "translate", "deliver"];

const isMs = value => Number.isInteger(value) && value >= 0;

export const isTrace = trace => !!trace && typeof trace.id === "string" && INPUTS.includes(trace.input)
    && typeof trace.stages === "object" && trace.stages !== null
    && typeof trace.outputs === "object" && trace.outputs !== null;

// Newest last. A trace that comes again (speech started) replaces its earlier copy in place.
export const mergeTrace = (traces, trace) => {
    if (!isTrace(trace)) return traces;
    const list = Array.isArray(traces) ? traces : [];
    const index = list.findIndex(row => row.id === trace.id);
    const next = index < 0 ? [...list, trace] : list.map((row, at) => at === index ? trace : row);
    return next.slice(-TRACE_KEEP);
};

// The most recent `count` traces, newest first; of one input when given.
export const latestTraces = (traces, count, input = null) => (Array.isArray(traces) ? traces : [])
    .filter(trace => input === null || trace.input === input).slice(-count).reverse();

// The stages before the outputs, as consecutive segments from the origin.
export const stageSegments = trace => {
    const segments = [];
    let at = 0;
    for (const kind of STAGES) {
        const ms = trace?.stages?.[kind];
        if (!isMs(ms)) continue;
        segments.push({ kind, start: at, ms });
        at += ms;
    }
    return segments;
};

// When each output was reached, from the origin. The conversion's round trip is added to
// speech that went through it, as a guide (it is the recent median, not this message's own).
export const outputArrivals = trace => {
    const rows = [];
    const chatbox = trace?.outputs?.chatbox;
    if (chatbox?.state === "sent" && isMs(chatbox.at_ms)) rows.push({ kind: "chatbox", at: chatbox.at_ms });
    const speech = trace?.outputs?.speech;
    if (speech?.state === "playing" && isMs(speech.at_ms)) {
        const conversion = speech.converted === true && isMs(speech.conversion_ms) ? speech.conversion_ms : null;
        rows.push({ kind: "speech", at: speech.at_ms, conversion, end: speech.at_ms + (conversion ?? 0) });
    }
    return rows;
};

// The time until the last output was reached, or the stages' end when nothing went out.
export const traceTotal = trace => {
    const ends = outputArrivals(trace).map(row => row.end ?? row.at);
    const stages = stageSegments(trace);
    if (stages.length) ends.push(stages.at(-1).start + stages.at(-1).ms);
    return ends.length ? Math.max(...ends) : null;
};

export const median = values => {
    const sorted = values.filter(isMs).sort((a, b) => a - b);
    return sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
};

// The axis of a timeline: the total rounded up to a readable step, so bars of different
// messages can be compared at a glance.
export const timelineScale = total => {
    if (!isMs(total) || total === 0) return 100;
    for (const step of [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 60000]) if (total <= step) return step;
    return Math.ceil(total / 60000) * 60000;
};

// How a duration is written everywhere in the flow: whole ms.
export const formatMs = ms => isMs(ms) ? `${ms} ms` : "—";

// Settings for the overlays: the desktop strip, and how many inputs each overlay lists.
export const overlayCount = settings => {
    const count = settings?.count;
    return Number.isInteger(count) && count >= 1 && count <= 3 ? count : 1;
};
