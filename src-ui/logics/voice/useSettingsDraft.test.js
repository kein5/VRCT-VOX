import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, stubGlobals, eventTarget } from "../test/hookHarness.js";
import { rebaseDraft } from "./draftRebase.js";

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
async function setup(context, savedFromResponse) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), requests = [];
    context.after(() => runtime.unmount());
    stubGlobals(context, { window: eventTarget() });
    const state = { saved: { vocabulary: { terms: [] }, model: "old" }, error: null };
    const { useSettingsDraft } = await loadModule(new URL("./useSettingsDraft.jsx", import.meta.url), runtime, {
        "./draftRebase": { rebaseDraft }, "./saveBar": { changedPaths: () => [], setSaveBarEntry() {} },
    });
    const write = value => new Promise(resolve => requests.push({ value, resolve }));
    const updateError = value => { state.error = value; };
    const render = () => {
        runtime.render(() => useSettingsDraft(state.saved, state.error, updateError, { write, savedFromResponse }));
        return runtime.render(() => useSettingsDraft(state.saved, state.error, updateError, { write, savedFromResponse }));
    };
    const edit = () => { render().setDraft({ ...state.saved, vocabulary: { terms: ["VRChat = ブイアールチャット"] } }); render(); };
    const reply = async (index, value) => {
        state.saved = value;
        render();
        requests[index].resolve({ status: 200, result: value });
        await flush();
        return render();
    };
    render();
    return { state, requests, render, edit, reply, write };
}

test("a successful write adopts canonical vocabulary and clears saving without a timeout", async context => {
    const s = await setup(context);
    s.edit(); s.render().submit(s.write); s.render();
    const canonical = { ...s.state.saved, vocabulary: { terms: ["VRChat=ブイアールチャット"] } };
    const form = await s.reply(0, canonical);
    assert.deepEqual(form.draft, canonical);
    assert.equal(form.dirty, false);
    assert.equal(form.saving, false);
    context.mock.timers.tick(5000);
    assert.equal(s.render().saveState, "saved");
});

test("a late owned acknowledgement clears uncertainty but discard revokes ownership", async context => {
    const s = await setup(context);
    s.edit(); s.render().submit(s.write); s.render();
    context.mock.timers.tick(5000); s.render();
    const canonical = { ...s.state.saved, vocabulary: { terms: ["VRChat=ブイアールチャット"] } };
    assert.equal((await s.reply(0, canonical)).saveState, "saved");
    s.edit(); s.render().submit(s.write); s.render();
    s.render().discard(); s.render();
    s.render().setDraft({ ...s.render().draft, model: "newer" }); s.render();
    assert.equal((await s.reply(1, canonical)).draft.model, "newer");
    assert.equal(s.render().saveState, "unsaved");
});

test("direct-voice responses acknowledge their nested settings without adopting runtime state", async context => {
    const s = await setup(context, value => value.settings);
    s.edit(); s.render().submit(s.write); s.render();
    const canonical = { ...s.state.saved, vocabulary: { terms: ["VRChat=ブイアールチャット"] } };
    s.state.saved = canonical;
    s.requests[0].resolve({ status: 200, result: { requested: false, generation: 3, settings: canonical } });
    await flush();
    assert.deepEqual(s.render().draft, canonical);
    assert.equal(s.render().saveState, "saved");
});

test("canonical acknowledgement preserves edits made after submission", async context => {
    const s = await setup(context);
    s.edit(); s.render().submit(s.write);
    s.render().setDraft({ ...s.render().draft, model: "newer" }); s.render();
    const canonical = { ...s.state.saved, vocabulary: { terms: ["VRChat=ブイアールチャット"] } };
    const form = await s.reply(0, canonical);
    assert.deepEqual(form.draft, { ...canonical, model: "newer" });
    assert.equal(form.dirty, true);
    assert.equal(form.saving, false);
});

test("editing back to the old saved value while saving survives the response atom update", async context => {
    const s = await setup(context);
    s.edit(); s.render().submit(s.write); s.render();
    s.render().setDraft({ ...s.render().draft, vocabulary: { terms: [] } }); s.render();
    const canonical = { ...s.state.saved, vocabulary: { terms: ["VRChat=ブイアールチャット"] } };
    const form = await s.reply(0, canonical);
    assert.deepEqual(form.draft.vocabulary.terms, []);
    assert.equal(form.dirty, true);
    assert.equal(form.saving, false);
});

test("an identical GET cannot acknowledge a write and an older response cannot confirm its retry", async context => {
    const s = await setup(context);
    s.edit(); s.render().submit(s.write); s.render();
    s.state.saved = structuredClone(s.requests[0].value); s.render();
    assert.equal(s.render().saving, true);
    context.mock.timers.tick(5000); s.render();
    assert.equal(s.state.error, "save_unconfirmed");
    s.state.error = null; s.render();
    assert.equal(s.render().saveState, "save_failed", "a refresh clearing the feature error still cannot confirm delivery");
    assert.equal(s.render().dirty, true);
    s.render().setDraft({ ...s.render().draft, model: "newer" }); s.render();
    s.render().submit(s.write); s.render();
    await s.reply(0, s.requests[0].value);
    assert.equal(s.render().saving, true);
    await s.reply(1, s.requests[1].value);
    assert.equal(s.render().saveState, "saved");
});

for (const response of [false, { status: 400 }]) test(`a rejected draft remains failed even after an identical refresh: ${JSON.stringify(response)}`, async context => {
    const s = await setup(context);
    s.edit();
    const saving = s.render().submit(s.write); s.render();
    s.state.saved = structuredClone(s.requests[0].value);
    s.state.error = "specific_backend_error";
    s.render();
    s.requests[0].resolve(response); await saving;
    assert.equal(s.render().dirty, true);
    assert.equal(s.render().saveState, "save_failed");
    assert.equal(s.state.error, "specific_backend_error");
    s.state.error = null;
    assert.equal(s.render().saveState, "save_failed");
    s.render().discard();
    assert.equal(s.render().saveState, "saved");
});
