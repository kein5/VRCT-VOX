import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../test/hookHarness.js";
import * as captions from "./realtimeCaptionState.js";
import { keepRecentLogs } from "../common/messageLogLimit.js";

const owner = { generation: 4, requested: true, state: "ready", namespace: "session" };
const payload = { source: "mic", namespace: "session", generation: 4, item_id: "one", revision: 1, state: "partial", text: "hello" };

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
        useStore_MessageLogs: () => ({ currentMessageLogs: runtime.store.get(Atom_MessageLogs), updateMessageLogs() {} }),
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
    render().messages.updateRealtimeCaption({ ...payload, revision: 3, state: "translated", text: "complete", translations: [{ message: "translation" }] });
    assert.equal(logs().data[0].realtime.state, "translated");
    render().messages.updateRealtimeCaption({ ...payload, item_id: "partial" });
    render().asr.updateState({ mic: { ...owner, state: "closed", requested: false } });
    assert.equal(logs().data.length, 1);
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
    unsubscribe();
});
