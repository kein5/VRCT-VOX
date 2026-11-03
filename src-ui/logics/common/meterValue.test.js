import assert from "node:assert/strict";
import { test } from "node:test";
import { loadModule } from "../test/hookHarness.js";
import { loadBridgeStore } from "../test/bridgeHarness.js";
import * as meterValue from "./meterValue.js";

test("both meter atoms preserve equal wrappers but publish state and value changes", async () => {
    const { runtime, stores } = await loadBridgeStore();
    for (const name of ["MicVolume", "SpeakerVolume"]) {
        const target = stores[`Atom_${name}`], hook = stores[`useStore_${name}`]();
        const update = hook[`update${name}`];
        const pending = runtime.store.get(target);
        update(0);
        const confirmed = runtime.store.get(target);
        assert.notStrictEqual(confirmed, pending);
        assert.equal(confirmed.state, "ok");
        for (let i = 0; i < 100; i++) update(0);
        assert.strictEqual(runtime.store.get(target), confirmed);
        update(1);
        const changed = runtime.store.get(target);
        assert.notStrictEqual(changed, confirmed);
        update(() => 1);
        assert.strictEqual(runtime.store.get(target), changed);
        update(1, { set_state: "error" });
        assert.equal(runtime.store.get(target).state, "error");
    }
    const target = stores.Atom_IsBackendReady, update = stores.useStore_IsBackendReady().updateIsBackendReady;
    update(false);
    const before = runtime.store.get(target);
    update(false);
    assert.notStrictEqual(runtime.store.get(target), before, "non-meter atom publication semantics stay unchanged");
});

test("useVolume only writes meter atoms; repeated samples and stop resets preserve wrappers", async () => {
    const { runtime, stores, jotai, subscriptions } = await loadBridgeStore();
    const { useVolume } = await loadModule(new URL("./useVolume.js", import.meta.url), runtime, {
        "@store": stores, jotai, "./meterValue.js": meterValue,
    });
    const volume = runtime.render(useVolume);
    assert.equal(subscriptions.includes(stores.Atom_MicVolume), false);
    assert.equal(subscriptions.includes(stores.Atom_SpeakerVolume), false);
    for (const [name, source] of [["MicVolume", "Mic"], ["SpeakerVolume", "Speaker"]]) {
        const target = stores[`Atom_${name}`];
        volume[`updateVolumeVariable_${source}`](0);
        const initial = runtime.store.get(target);
        for (let i = 0; i < 100; i++) volume[`updateVolumeVariable_${source}`](0);
        assert.strictEqual(runtime.store.get(target), initial);
        volume[`update${source}ThresholdCheckStatus`](false);
        const stopped = runtime.store.get(target);
        assert.equal(stopped.data, "0");
        volume[`update${source}ThresholdCheckStatus`](false);
        assert.strictEqual(runtime.store.get(target), stopped);
    }
});
