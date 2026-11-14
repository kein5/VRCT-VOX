import { test } from "node:test";
import assert from "node:assert/strict";
import { flowNote, offGroups, outputDetail, outputTime, stripItems, timelineRows } from "./flowText.js";

const t = (key, options) => options ? `${key}:${JSON.stringify(options)}` : key;
const names = { language: name => `lang(${name})` };
const trace = (id, input, outputs, stages = {}, extra = {}) => ({ id, input, text: `text ${id}`, translation: "", origin: "final",
    stages, outputs, ...extra });

test("each output of the route map says what it does, or why it is not used", () => {
    assert.equal(outputDetail({ id: "chatbox", on: true, content: "both" }, t, names), "io_flow.content.both");
    assert.equal(outputDetail({ id: "chatbox", on: false, reason: "vrchat_off" }, t, names), "io_flow.reason.vrchat_off");
    assert.equal(outputDetail({ id: "speech", on: true, path: "converted", language: "English" }, t, names),
        'io_flow.speech_language:{"language":"lang(English)"} · io_flow.speech_path.converted');
    assert.equal(outputDetail({ id: "live_voice", on: true, carried: "converted", engine: "rvc", during_speech: "suppress" }, t, names),
        'io_flow.live.converted:{"engine":"RVC"} · io_flow.during_speech.suppress');
    assert.equal(outputDetail({ id: "live_voice", on: true, carried: "vrchat_mic", during_speech: null }, t, names), "io_flow.live.vrchat_mic");
    assert.equal(outputDetail({ id: "websocket", on: true }, t, names), "io_flow.used");
});

test("unused outputs fold into one line per reason, in their order", () => {
    const rows = [{ id: "chatbox", on: true }, { id: "vr_log", on: false, reason: "setting_off" },
        { id: "speech", on: false, reason: "tts_off" }, { id: "websocket", on: false, reason: "setting_off" }];
    assert.deepEqual(offGroups(rows, t), [
        { reason: "setting_off", outputs: "io_flow.output.vr_logio_flow.list_separatorio_flow.output.websocket", text: "io_flow.reason.setting_off" },
        { reason: "tts_off", outputs: "io_flow.output.speech", text: "io_flow.reason.tts_off" }]);
    assert.deepEqual(offGroups(undefined, t), []);
});

test("the latest message's time for an output is in ms, or its state when it did not go out", () => {
    const row = trace("a", "voice", { chatbox: { state: "sent", at_ms: 240 },
        speech: { state: "playing", at_ms: 800, converted: true, conversion_ms: 31 } });
    assert.equal(outputTime({ id: "chatbox" }, row, t), "240 ms");
    assert.equal(outputTime({ id: "speech" }, row, t), "831 ms");
    assert.equal(outputTime({ id: "chatbox" }, trace("b", "chat", { chatbox: { state: "off", at_ms: null } }), t), "io_flow.state.off");
    assert.equal(outputTime({ id: "desktop_caption" }, row, t), null);
    assert.equal(outputTime({ id: "chatbox" }, null, t), null);
});

test("a timeline lists the stages in order, then each arrival, then what did not go out", () => {
    const rows = timelineRows(trace("a", "voice", { chatbox: { state: "sent", at_ms: 240 },
        speech: { state: "playing", at_ms: 800, converted: true, conversion_ms: 31 } }, { wait: 10, translate: 200 }), t);
    assert.deepEqual(rows.map(row => [row.kind, row.value, row.start, row.end]), [
        ["stage", "10 ms", 0, 10], ["stage", "200 ms", 10, 210], ["chatbox", "240 ms", 0, 240],
        ["speech", "800 ms", 0, 800], ["conversion", "31 ms", 800, 831]]);
    const off = timelineRows(trace("b", "chat", { chatbox: { state: "off", at_ms: null } }), t);
    assert.deepEqual(off, [{ kind: "chatbox", label: "io_flow.output_short.chatbox", value: "io_flow.state.off", start: 0, end: 0, off: true }]);
});

test("the desktop strip lists the newest inputs first, worded, and fits the overlay's limits", () => {
    const traces = [trace("1", "voice", { chatbox: { state: "sent", at_ms: 300 } }),
        trace("2", "chat", { chatbox: { state: "sent", at_ms: 120 } }, {}, { translation: "hola" })];
    const [first, second] = stripItems(traces, 2, t);
    assert.equal(first.id, "2");
    assert.equal(first.label, "io_flow.chat");
    assert.equal(first.text, "text 2 → hola");
    assert.equal(first.scale, 200);
    assert.equal(second.scale, 500);
    assert.equal(stripItems(traces, 1, t).length, 1);
    const long = stripItems([trace("3", "voice", { speech: { state: "playing", at_ms: 900000, converted: false } }, {}, { text: "x".repeat(300) })], 1, t)[0];
    assert.equal(long.text.length, 200);
    assert.ok(long.rows.every(row => row.end <= long.scale && long.scale <= 600000));
});

test("the note under the strip is the conversion's round trip while it runs", () => {
    assert.equal(flowNote({ conversion_round_trip_ms: 31 }, t), 'io_flow.conversion_live:{"ms":31}');
    assert.equal(flowNote({ conversion_round_trip_ms: null }, t), "");
    assert.equal(flowNote(null, t), "");
});
