import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../test/hookHarness.js";
import * as captions from "./realtimeCaptionState.js";
import { keepRecentLogs } from "../common/messageLogLimit.js";

const owner = { generation: 4, requested: true, state: "ready", namespace: "session" };
const payload = { source: "mic", namespace: "session", generation: 4, item_id: "one", revision: 1, state: "partial", text: "hello" };

for (const source of ["mic", "speaker"]) {
    for (const [outcome, status, reason] of [["delivered", "ok", null], ["not_delivered", "not_sent", "expired"],
        ["not_delivered", "not_sent", "revoked"], ["not_delivered", "not_sent", "superseded"],
        ["not_delivered", "not_sent", "filtered"], ["failed", "failed", "processing_failed"]]) {
        test(`${source} recognized row stays pending until ${outcome}/${reason}`, () => {
            const event = { ...payload, source, state: "final" };
            const active = { [source]: owner };
            const final = captions.applyRealtimeCaption({ rows: [], retired: [] }, event, active);
            assert.equal(final.rows[0].status, "pending");
            const translated = captions.applyRealtimeCaption(final, { ...event, state: "translated", revision: 2,
                translations: [{ message: "訳", transliteration: [] }] }, active);
            assert.equal(translated.rows[0].status, "pending");
            // Terminal notifications remain useful after a stop or a new session.
            const result = { ...event, state: "outcome", text: undefined, revision: 3, outcome, reason };
            const settled = captions.applyRealtimeCaption(translated, result, {});
            assert.equal(settled.rows[0].status, status);
            assert.equal(settled.rows[0].category, source === "mic" ? "sent" : "received");
            assert.equal(settled.rows[0].created_at, final.rows[0].created_at);
            assert.equal(settled.rows[0].messages, translated.rows[0].messages);
            for (const later of [result, { ...result, revision: 100, outcome: "delivered" },
                { ...result, revision: 100, outcome: "failed" }, { ...event, revision: 100 },
                { ...event, revision: 100, state: "partial" }, { ...event, revision: 100, state: "translated" }]) {
                assert.equal(captions.applyRealtimeCaption(settled, later, active), settled);
            }
        });
    }
}

test("a speaker caption keeps the speakers its final names, through translation and the outcome", () => {
    const active = { speaker: owner }, event = { ...payload, source: "speaker" };
    const partial = captions.applyRealtimeCaption({ rows: [], retired: [] }, { ...event, speakers: [] }, active);
    assert.equal("speakers" in partial.rows[0], false);
    const final = captions.applyRealtimeCaption(partial, { ...event, revision: 2, state: "final", speakers: ["C", "B"] }, active);
    assert.deepEqual(final.rows[0].speakers, ["C", "B"]);
    // The translated row is built again from its payload; one without the list keeps what the final said.
    for (const speakers of [["C", "B"], undefined]) {
        const translated = captions.applyRealtimeCaption(final, { ...event, revision: 3, state: "translated", speakers,
            translations: [{ message: "訳", transliteration: [] }] }, active);
        assert.deepEqual(translated.rows[0].speakers, ["C", "B"]);
        const settled = captions.applyRealtimeCaption(translated, { ...event, text: undefined, revision: 4, state: "outcome", outcome: "delivered" }, {});
        assert.deepEqual(settled.rows[0].speakers, ["C", "B"]);
    }
});

test("speakers that are not short capital labels, or that come for the microphone, are left out", () => {
    const row = (source, speakers) => captions.applyRealtimeCaption({ rows: [], retired: [] },
        { ...payload, source, state: "final", speakers }, { [source]: owner }).rows[0];
    for (const speakers of ["A", [1], ["a"], [""], ["ABCD"], ["A", "B", "C", "D", "E"], [["A"]], null, {}]) {
        assert.equal("speakers" in row("speaker", speakers), false, JSON.stringify(speakers));
    }
    assert.equal("speakers" in row("mic", ["A"]), false);
    assert.deepEqual(row("speaker", ["A", "AB", "ABC"]).speakers, ["A", "AB", "ABC"]);
});

test("outcomes cannot create rows or settle another caption identity or a partial", () => {
    const empty = { rows: [], retired: [] };
    const event = { ...payload, state: "outcome", revision: 3, outcome: "delivered" };
    assert.equal(captions.applyRealtimeCaption(empty, event, { mic: owner }), empty);
    const partial = captions.applyRealtimeCaption(empty, payload, { mic: owner });
    assert.equal(captions.applyRealtimeCaption(partial, event, { mic: owner }), partial);
    const final = captions.applyRealtimeCaption(partial, { ...payload, revision: 2, state: "final" }, { mic: owner });
    for (const changes of [{ source: "speaker" }, { generation: 5 }, { namespace: "new" }, { item_id: "new" },
        { outcome: "unknown" }, { outcome: "toString" }, { revision: 2 }]) {
        assert.equal(captions.applyRealtimeCaption(final, { ...event, ...changes }, { mic: owner }), final);
    }
    const pruned = { rows: [], retired: [final.rows[0].id] };
    assert.equal(captions.applyRealtimeCaption(pruned, event, { mic: owner }), pruned);
});

test("equal realtime rows retain state; generations and namespaces still publish", () => {
    const state = { mic: owner, speaker: { ...owner, namespace: "speaker" } };
    assert.equal(captions.mergeRealtimeState(state, { mic: { ...owner } }), state);
    assert.equal(captions.mergeRealtimeState(state, { mic: { ...owner, namespace: null } }), state);
    const next = captions.mergeRealtimeState(state, { mic: { ...owner, generation: 5 } });
    assert.notEqual(next, state);
    assert.equal(next.speaker, state.speaker);
    assert.equal(captions.mergeRealtimeState(next, state), next);
    assert.notEqual(captions.mergeRealtimeState(state, { mic: { ...owner, namespace: "new" } }), state);
    assert.equal(captions.mergeRealtimeState(state, { mic: { ...owner, state: "starting" } }), state);
    for (const phase of ["stopping", "closed", "failed"]) {
        const stopped = captions.mergeRealtimeState(state, { mic: { ...owner, state: phase, requested: false } });
        assert.equal(captions.mergeRealtimeState(stopped, state), stopped);
    }
});

test("caption pruning retains unchanged lists and retires only stale partial captions", () => {
    const partial = captions.applyRealtimeCaption({ rows: [], retired: [] }, payload, { mic: owner });
    assert.equal(captions.pruneRealtimeCaptions(partial, { mic: owner }), partial);
    const final = captions.applyRealtimeCaption(partial, { ...payload, item_id: "final", state: "final" }, { mic: owner });
    const pruned = captions.pruneRealtimeCaptions(final, { mic: { ...owner, requested: false } });
    assert.equal(pruned.rows.length, 1);
    assert.equal(pruned.rows[0].realtime.state, "final");
    assert.deepEqual(pruned.retired, [partial.rows[0].id]);
    assert.equal(captions.pruneRealtimeCaptions(pruned, {}), pruned);
    assert.equal(captions.applyRealtimeCaption(pruned, { ...payload, revision: 2 }, { mic: owner }), pruned);
});

test("production realtime and message hooks preserve logs on polls and handle captions, stop and settings invalidation", async () => {
    const runtime = hooks(), Atom_MessageLogs = runtime.jotai.atom({ state: "ok", data: [] });
    const storeImports = {
        Atom_MessageLogs, store: {},
        useStore_MessageLogs: () => ({ currentMessageLogs: runtime.store.get(Atom_MessageLogs),
            updateMessageLogs(update) { runtime.store.set(Atom_MessageLogs, value => ({ ...value, data: update(value) })); } }),
        useStore_MessageInputValue: () => ({ currentMessageInputValue: { data: "" }, updateMessageInputValue() {} }),
    };
    const realtime = await loadModule(new URL("./useRealtimeASR.js", import.meta.url), runtime, {
        "@store": storeImports, "./realtimeCaptionState": captions,
    });
    const { useMessage } = await loadModule(new URL("../common/useMessage.js", import.meta.url), runtime, {
        "@store": storeImports, "../transcription/useRealtimeASR": realtime,
        "../transcription/realtimeCaptionState": captions, "./messageLogLimit": { keepRecentLogs },
    });
    const render = () => runtime.render(() => ({ asr: realtime.useRealtimeASR(), messages: useMessage() }));
    const logs = () => runtime.store.get(Atom_MessageLogs);
    let logChanges = 0;
    const unsubscribe = runtime.store.sub(Atom_MessageLogs, () => logChanges++);
    render().asr.updateState({ mic: { ...owner, state: "starting", namespace: null } });
    assert.equal(logChanges, 0);
    const starting = render().asr.state;
    render().messages.updateRealtimeCaption({ ...payload, namespace: "unknown", state: "outcome", outcome: "delivered" });
    assert.equal(render().asr.state, starting);
    assert.equal(logChanges, 0);
    // A caption can bind the namespace before the first ready poll arrives.
    render().messages.updateRealtimeCaption(payload);
    assert.equal(render().asr.state.mic.namespace, "session");
    assert.equal(logs().data.length, 1);
    const before = logs(), state = render().asr.state;
    render().asr.updateState({ mic: { ...owner, state: "starting", namespace: null } });
    assert.equal(render().asr.state, state);
    assert.equal(logs(), before);
    assert.equal(logChanges, 1);
    render().messages.updateRealtimeCaption({ ...payload, revision: 2, state: "final", text: "complete" });
    render().messages.failSentMessageLog({});
    assert.equal(logs().data[0].status, "pending");
    render().messages.updateRealtimeCaption({ ...payload, revision: 3, state: "translated", text: "complete", translations: [{ message: "translation" }] });
    assert.equal(logs().data[0].realtime.state, "translated");
    assert.equal(logs().data[0].status, "pending");
    render().messages.updateRealtimeCaption({ ...payload, item_id: "partial" });
    render().asr.updateState({ mic: { ...owner, state: "closed", requested: false } });
    assert.equal(logs().data.length, 1);
    render().messages.updateRealtimeCaption({ ...payload, revision: 4, state: "outcome", outcome: "not_delivered", reason: "revoked" });
    assert.equal(logs().data[0].status, "not_sent");
    const stoppedLogs = logs(), stopped = render().asr.state;
    render().asr.updateState({ mic: { ...owner } });
    render().messages.updateRealtimeCaption({ ...payload, item_id: "late" });
    assert.equal(render().asr.state, stopped);
    assert.equal(logs(), stoppedLogs);
    render().asr.updateState({ mic: { ...owner, generation: 5, namespace: "new" } });
    const newCaption = { ...payload, generation: 5, namespace: "new", item_id: "new" };
    render().messages.updateRealtimeCaption(newCaption);
    const settings = { server: "bundled", model: "first", mic: {}, speaker: {} };
    render().asr.updateSettings(settings);
    render().asr.updateSettings({ ...settings, model: "changed" });
    assert.equal(render().asr.state.mic.state, "stopping");
    assert.equal(logs().data.length, 1);
    // Even an equal poll must prune a partial added since the last state update.
    runtime.store.set(Atom_MessageLogs, { ...logs(), data: [...logs().data, { id: "stale", realtime: { ...newCaption } }] });
    const invalidated = render().asr.state;
    render().asr.updateState({ mic: { ...invalidated.mic } });
    assert.equal(render().asr.state, invalidated);
    assert.equal(logs().data.length, 1);
    assert.ok(runtime.store.get(realtime.realtimeRetiredAtom).includes("stale"));
    render().asr.updateState({ mic: { ...owner, generation: 6, namespace: "restart" } });
    render().messages.updateRealtimeCaption({ ...payload, generation: 6, namespace: "restart", state: "final" });
    render().messages.updateRealtimeCaption({ ...payload, generation: 6, namespace: "restart", item_id: "partial" });
    render().asr.backendStopped();
    assert.deepEqual(logs().data.map(row => row.status), ["not_sent", "failed"]);
    assert.equal(logs().data[1].realtime.reason, "backend_unavailable");
    const lostLogs = logs();
    render().messages.updateRealtimeCaption({ ...payload, generation: 6, namespace: "restart", revision: 3, state: "outcome", outcome: "delivered" });
    assert.equal(logs(), lostLogs);
    unsubscribe();
});
