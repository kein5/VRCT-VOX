import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildFlowGraph } from "./flowGraph.js";

const sample = JSON.parse(readFileSync(new URL("../../../tests/voice/fixtures/io_flow_sample.json", import.meta.url), "utf8"));
const edge = (graph, id) => graph.edges.find(row => row.id === id);
const node = (graph, id) => graph.nodes.find(row => row.id === id);

test("each input is wired to the outputs the settings send it to", () => {
    const graph = buildFlowGraph(sample.flow, sample.traces);
    assert.equal(edge(graph, "translate_voice>chatbox").on, true);
    assert.equal(edge(graph, "translate_chat>chatbox").on, true);
    assert.equal(edge(graph, "translate_voice>vr_log").on, false, "off in the settings");
    assert.equal(edge(graph, "translate_chat>speech").on, false, "chat is not spoken");
    assert.equal(edge(graph, "translate_chat>clipboard"), undefined, "chat never reaches the clipboard");
    // Speech and the live voice both go through the conversion to the mic VRChat hears.
    assert.equal(edge(graph, "speech>conversion").on, true);
    assert.equal(edge(graph, "in_voice>conversion").on, true);
    assert.equal(edge(graph, "conversion>live_voice").on, true);
    assert.equal(node(graph, "conversion").ms, 31);
});

test("the newest message's path lights up, and only the outputs it reached", () => {
    const graph = buildFlowGraph(sample.flow, sample.traces);
    // The sample's newest is a chat that reached the chatbox only.
    assert.deepEqual(graph.edges.filter(row => row.lit).map(row => row.id).sort(),
        ["in_chat>translate_chat", "translate_chat>chatbox"]);
    const voiceFirst = buildFlowGraph(sample.flow, sample.traces.filter(row => row.id !== "c2"));
    assert.deepEqual(voiceFirst.edges.filter(row => row.lit).map(row => row.id).sort(), [
        "conversion>live_voice", "in_voice>recognition", "recognition>translate_voice", "speech>conversion",
        "translate_voice>chatbox", "translate_voice>speech"]);
    assert.notEqual(graph.pulse, voiceFirst.pulse, "a new message pulses again");
});

test("outputs carry the latest time of each input", () => {
    const graph = buildFlowGraph(sample.flow, sample.traces);
    assert.deepEqual(node(graph, "chatbox").times, { voice: 226, chat: 209 });
    assert.deepEqual(node(graph, "live_voice").times, { voice: 851, chat: null });
    assert.equal(node(graph, "translate_voice").ms, 212);
});

test("without the conversion, speech goes straight to the mic; VRChat reading the mic itself is shown apart", () => {
    const voice = { ...sample.flow.voice, outputs: sample.flow.voice.outputs.map(row =>
        row.id === "live_voice" ? { ...row, carried: "vrchat_mic", engine: null, during_speech: null }
            : row.id === "speech" ? { ...row, path: "device" } : row) };
    const graph = buildFlowGraph({ ...sample.flow, voice, conversion_round_trip_ms: null }, []);
    assert.equal(node(graph, "conversion"), undefined);
    assert.equal(edge(graph, "speech>live_voice").on, true);
    const direct = edge(graph, "in_voice>live_voice");
    assert.equal(direct.on, false);
    assert.equal(direct.direct, true);
    assert.equal(graph.edges.some(row => row.lit), false, "nothing measured, nothing lit");
    assert.equal(buildFlowGraph(null, []), null);
});
