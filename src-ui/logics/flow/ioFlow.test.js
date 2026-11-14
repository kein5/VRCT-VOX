import { test } from "node:test";
import assert from "node:assert/strict";
import { TRACE_KEEP, formatMs, latestTraces, median, mergeTrace, outputArrivals, overlayCount, stageSegments,
    timelineScale, traceTotal } from "./ioFlow.js";

const trace = (id, input = "voice", outputs = {}, stages = {}) => ({ id, input, text: id, translation: "", origin: "final",
    stages, outputs });

test("a trace that comes again replaces its copy in place; old ones drop off", () => {
    let list = mergeTrace([], trace("a"));
    list = mergeTrace(list, trace("b", "chat"));
    list = mergeTrace(list, { ...trace("a"), outputs: { speech: { state: "playing", at_ms: 900 } } });
    assert.deepEqual(list.map(row => row.id), ["a", "b"]);
    assert.equal(list[0].outputs.speech.at_ms, 900);
    assert.equal(mergeTrace(list, { id: "x", input: "speaker" }), list, "not a trace of the user's own input");
    for (let index = 0; index < TRACE_KEEP + 5; index++) list = mergeTrace(list, trace(`n${index}`));
    assert.equal(list.length, TRACE_KEEP);
    assert.equal(list.at(-1).id, `n${TRACE_KEEP + 4}`);
});

test("the latest traces come newest first, of one input when asked", () => {
    const list = [trace("1"), trace("2", "chat"), trace("3"), trace("4")];
    assert.deepEqual(latestTraces(list, 2).map(row => row.id), ["4", "3"]);
    assert.deepEqual(latestTraces(list, 3, "chat").map(row => row.id), ["2"]);
    assert.deepEqual(latestTraces(null, 1), []);
});

test("stages run one after another from the origin; outputs carry their own arrival", () => {
    const row = trace("a", "voice", {
        chatbox: { state: "sent", at_ms: 240 },
        speech: { state: "playing", at_ms: 820, converted: true, conversion_ms: 31 },
    }, { wait: 12, translate: 210 });
    assert.deepEqual(stageSegments(row), [{ kind: "wait", start: 0, ms: 12 }, { kind: "translate", start: 12, ms: 210 }]);
    assert.deepEqual(outputArrivals(row), [{ kind: "chatbox", at: 240 },
        { kind: "speech", at: 820, conversion: 31, end: 851 }]);
    assert.equal(traceTotal(row), 851);
});

test("outputs that did not go out have no arrival, and the total falls back to the stages", () => {
    const row = trace("a", "chat", { chatbox: { state: "off", at_ms: null }, speech: { state: "queued", at_ms: null } },
        { translate: 300 });
    assert.deepEqual(outputArrivals(row), []);
    assert.equal(traceTotal(row), 300);
    assert.equal(traceTotal(trace("b")), null);
    // Speech without the conversion adds nothing.
    assert.deepEqual(outputArrivals(trace("c", "chat", { speech: { state: "playing", at_ms: 500, converted: false } })),
        [{ kind: "speech", at: 500, conversion: null, end: 500 }]);
});

test("durations are whole ms, and the axis rounds up to a readable step", () => {
    assert.equal(formatMs(851), "851 ms");
    assert.equal(formatMs(null), "—");
    assert.equal(formatMs(1.5), "—");
    assert.equal(timelineScale(851), 1000);
    assert.equal(timelineScale(1001), 2000);
    assert.equal(timelineScale(0), 100);
    assert.equal(timelineScale(130000), 180000);
    assert.equal(median([900, 100, 500, null]), 500);
    assert.equal(median([]), null);
});

test("the overlays list one input unless the setting says two or three", () => {
    assert.equal(overlayCount(undefined), 1);
    assert.equal(overlayCount({ count: 3 }), 3);
    assert.equal(overlayCount({ count: 4 }), 1);
});
