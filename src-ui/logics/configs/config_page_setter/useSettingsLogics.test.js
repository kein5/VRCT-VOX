import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule } from "../../test/hookHarness.js";

async function setup(context) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), requests = [];
    context.after(() => runtime.unmount());
    let entry;
    const { useSaveButtonLogic } = await loadModule(new URL("./useSettingsLogics.js", import.meta.url), runtime, {
        "@store": {}, "@logics_common": {}, "@utils": {},
        "../../voice/saveBar": { setSaveBarEntry: (_id, value) => { entry = value; } },
    });
    const props = { variable: "old", state: "ok", label: "Field",
        setFunction: value => new Promise(resolve => requests.push({ value, resolve })) };
    const render = () => {
        runtime.render(useSaveButtonLogic, props);
        return runtime.render(useSaveButtonLogic, props);
    };
    render();
    return { props, requests, render, get entry() { return entry; } };
}

for (const result of [false, { status: 400, result: { data: "old" } }]) {
    test(`text save retains its draft and reports failure on ${JSON.stringify(result)}`, async context => {
        const s = await setup(context);
        s.render().onChangeFunction("attempted");
        const saving = s.render().saveFunction();
        s.props.state = "pending"; s.render();
        s.props.state = "ok"; s.render();
        s.requests[0].resolve(result); await saving;
        assert.equal(s.render().variable, "attempted");
        assert.equal(s.entry.saveState, "save_failed");
        assert.equal(s.entry.edited, true);
        const retry = s.entry.save();
        assert.equal(s.requests[1].value, "attempted");
        s.props.variable = "canonical"; s.render();
        s.requests[1].resolve({ status: 200, result: "canonical" }); await retry;
        assert.equal(s.render().variable, "canonical");
        assert.equal(s.entry.saveState, "saved");
    });
}

test("batched transport failure and thrown saves preserve text until explicit discard", async context => {
    const s = await setup(context);
    s.render().onChangeFunction("draft");
    s.props.setFunction = async () => false;
    await s.render().saveFunction();
    assert.equal(s.render().variable, "draft");
    assert.equal(s.entry.saveState, "save_failed");
    s.props.setFunction = async () => { throw new Error("transport"); };
    await s.render().saveFunction();
    assert.equal(s.render().variable, "draft");
    s.entry.discard();
    assert.equal(s.render().variable, "old");
    assert.equal(s.entry.saveState, "saved");
});

test("text saves await their own response, preserve later edits and ignore discarded responses", async context => {
    const s = await setup(context);
    s.render().onChangeFunction("first");
    const saving = s.render().saveFunction(); s.render();
    s.props.variable = "first"; s.render(); // A GET is not an acknowledgement.
    assert.equal(s.entry.saveState, "saving");
    context.mock.timers.tick(5000); s.render();
    assert.equal(s.entry.saveState, "save_failed");
    s.render().onChangeFunction("newer"); s.render();
    s.requests[0].resolve({ status: 200, result: "first" }); await saving;
    assert.equal(s.render().variable, "newer");
    const second = s.entry.save(); s.render();
    s.entry.discard(); s.render().onChangeFunction("latest"); s.render();
    s.requests[1].resolve({ status: 400 }); await second;
    assert.equal(s.render().variable, "latest");
    assert.equal(s.entry.saveState, "unsaved");
});

test("VR sliders can hand edits to the parent debounce synchronously", async context => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const writes = [], runtime = hooks();
    const props = { variable: 0, min: 0, max: 1, setter_timing: "on_change", debounce_ms: 0,
        setterFunction: value => writes.push(value) };
    const { useSliderLogic } = await loadModule(new URL("./useSettingsLogics.js", import.meta.url), runtime, {
        "@store": {}, "@logics_common": {}, "@utils": {}, "../../voice/saveBar": {},
    });
    runtime.render(useSliderLogic, props).onChangeFunction(0.1);
    assert.deepEqual(writes, [0.1]);
    runtime.unmount();
});

test("text acknowledgement preserves an edit back to the old value in a batched render", async context => {
    const s = await setup(context);
    s.render().onChangeFunction("attempted");
    const saving = s.render().saveFunction(); s.render();
    s.render().onChangeFunction("old"); s.render();
    s.props.variable = "canonical";
    s.requests[0].resolve({ status: 200, result: "canonical" }); await saving;
    assert.equal(s.render().variable, "old");
    assert.equal(s.entry.saveState, "unsaved");
});
