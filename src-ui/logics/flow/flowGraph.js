// The flow panel's graph: which input reaches which output, as boxes and arrows.
// Built from the route map (/get/data/io_flow) and the recent traces; pure, so the panel,
// the VR window and the tests share it. The view places the boxes on a grid and draws the
// arrows between them; this decides only what exists, what is in use and what lights up.
import { latestTraces, outputArrivals } from "./ioFlow.js";

// The outputs on the right, top to bottom. "live_voice" is what VRChat hears as the user's mic.
export const GRAPH_OUTPUTS = ["chatbox", "live_voice", "desktop_caption", "vr_log", "clipboard", "websocket"];

const byId = lane => Object.fromEntries((lane?.outputs ?? []).map(row => [row.id, row]));

const arrivalsOf = trace => Object.fromEntries(outputArrivals(trace).map(row => [row.kind, row]));

export const buildFlowGraph = (flow, traces) => {
    if (!flow?.voice || !flow?.chat) return null;
    const voice = byId(flow.voice), chat = byId(flow.chat);
    const latest = { voice: latestTraces(traces, 1, "voice")[0] ?? null, chat: latestTraces(traces, 1, "chat")[0] ?? null };
    const arrivals = { voice: arrivalsOf(latest.voice), chat: arrivalsOf(latest.chat) };
    const live = voice.live_voice ?? { on: false, carried: "vrchat_mic" };
    const speech = { voice: voice.speech ?? { on: false }, chat: chat.speech ?? { on: false } };
    const converted = live.carried === "converted"
        || speech.voice.path === "converted" || speech.chat.path === "converted";

    const nodes = [
        { id: "in_voice", kind: "input", lane: "voice", on: flow.voice.on === true },
        { id: "recognition", kind: "stage", lane: "voice", on: flow.voice.on === true, ...flow.voice.recognition,
            ms: latest.voice?.stages?.recognition ?? latest.voice?.stages?.wait ?? null,
            msKind: latest.voice?.stages?.recognition !== undefined ? "recognition" : "wait" },
        { id: "translate_voice", kind: "stage", lane: "voice", on: flow.voice.translation?.on === true,
            translation: flow.voice.translation, ms: latest.voice?.stages?.translate ?? null },
        { id: "in_chat", kind: "input", lane: "chat", on: true },
        { id: "translate_chat", kind: "stage", lane: "chat", on: flow.chat.translation?.on === true,
            translation: flow.chat.translation, ms: latest.chat?.stages?.translate ?? null },
        { id: "speech", kind: "speech", on: speech.voice.on === true || speech.chat.on === true,
            language: speech.voice.language ?? speech.chat.language ?? null },
    ];
    if (converted) nodes.push({ id: "conversion", kind: "conversion", on: true, engine: live.engine ?? null,
        ms: Number.isInteger(flow.conversion_round_trip_ms) ? flow.conversion_round_trip_ms : null });
    for (const id of GRAPH_OUTPUTS) {
        const rows = { voice: voice[id], chat: chat[id] };
        const on = id === "live_voice" ? live.on === true || speech.voice.on === true || speech.chat.on === true
            : rows.voice?.on === true || rows.chat?.on === true;
        // Reached by speech: the time it began; by text: the time it was sent.
        const time = lane => id === "live_voice" ? (arrivals[lane].speech?.end ?? null)
            : id === "chatbox" ? (arrivals[lane].chatbox?.at ?? null) : null;
        nodes.push({ id, kind: "output", on, rows, live: id === "live_voice" ? live : null,
            times: { voice: time("voice"), chat: time("chat") } });
    }

    const edges = [];
    const edge = (from, to, lane, on, extra = {}) => edges.push({ id: `${from}>${to}`, from, to, lane, on: on === true, ...extra });
    // Text: the recognized speech and the typed chat, through translation, to each output.
    edge("in_voice", "recognition", "voice", flow.voice.on);
    edge("recognition", "translate_voice", "voice", flow.voice.on);
    edge("in_chat", "translate_chat", "chat", true);
    for (const id of ["chatbox", "desktop_caption", "vr_log", "clipboard", "websocket"]) {
        if (voice[id]) edge("translate_voice", id, "voice", voice[id].on);
        if (chat[id]) edge("translate_chat", id, "chat", chat[id].on);
    }
    // Speech: either lane's text is spoken, through the conversion when it runs, to the mic VRChat hears.
    edge("translate_voice", "speech", "voice", speech.voice.on);
    edge("translate_chat", "speech", "chat", speech.chat.on);
    const speechOn = speech.voice.on === true || speech.chat.on === true;
    const speechConverted = speech.voice.path === "converted" || speech.chat.path === "converted";
    if (speechConverted) edge("speech", "conversion", "speech", speechOn);
    else edge("speech", "live_voice", "speech", speechOn && live.carried !== "muted");
    // The live voice: converted, passed through, or read by VRChat itself (not through the app).
    if (live.carried === "converted") {
        edge("in_voice", "conversion", "voice", true);
    } else {
        edge("in_voice", "live_voice", "voice", live.carried === "passthrough", { direct: live.carried === "vrchat_mic" });
    }
    if (converted) edge("conversion", "live_voice", "speech", live.carried !== "muted");

    // Light the path of the newest message: where it went, and nothing it did not reach.
    const newest = latestTraces(traces, 1)[0] ?? null;
    const lit = new Set();
    if (newest) {
        const lane = newest.input, translate = `translate_${lane}`, reached = arrivals[lane];
        const path = lane === "voice" ? ["in_voice>recognition", "recognition>translate_voice"] : ["in_chat>translate_chat"];
        if (reached.chatbox) path.push(`${translate}>chatbox`);
        if (reached.speech) {
            path.push(`${translate}>speech`);
            path.push(speechConverted ? "speech>conversion" : "speech>live_voice");
            if (speechConverted) path.push("conversion>live_voice");
        }
        if (reached.chatbox || reached.speech) path.forEach(id => lit.add(id));
    }
    for (const row of edges) row.lit = row.on && lit.has(row.id);
    const pulse = newest ? `${newest.id}:${Object.keys(arrivals[newest.input]).sort().join(",")}` : null;
    return { nodes, edges, pulse, latest, newest };
};
