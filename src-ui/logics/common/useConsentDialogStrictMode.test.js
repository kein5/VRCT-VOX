import assert from "node:assert/strict";
import { test } from "node:test";
import { loadModule, hooks, stubGlobals } from "../test/hookHarness.js";

// StrictMode runs mount, cleanup and mount again with the same refs. The native
// dialog's close() can leave focus on the body before the replayed effect runs.
test("a StrictMode effect replay keeps the original opener for focus return", async t => {
    const refs = [];
    let effect = null, refIndex = 0;
    const react = {
        useRef: initial => (refs[refIndex] ??= { current: initial }, refs[refIndex++]),
        useEffect: fn => { effect = fn; },
    };
    const body = { tagName: "BODY" };
    const focused = [];
    const opener = { isConnected: true, disabled: false, tabIndex: 0, matches: () => false,
        getAttribute: () => null, closest: () => null, focus: () => { focused.push("opener"); } };
    const doc = { activeElement: opener, body };
    stubGlobals(t, { document: doc });
    const modal = { open: false, contains: () => false,
        showModal() { this.open = true; doc.activeElement = { tagName: "A" }; },
        close() { this.open = false; doc.activeElement = body; } };
    const { useConsentDialog } = await loadModule(new URL("./useConsentDialog.js", import.meta.url), hooks(),
        { react });
    const render = open => {
        refIndex = 0;
        const result = useConsentDialog(open, { current: null });
        result.dialog.current = modal;
        return result;
    };

    render(true);
    const cleanupFirst = effect();
    cleanupFirst();
    const cleanupReplay = effect();
    await Promise.resolve();
    assert.equal(modal.open, true, "the replayed effect reopened the dialog");
    assert.deepEqual(focused, [], "the replay does not move focus out of the open dialog");

    render(false);
    cleanupReplay();
    effect();
    await Promise.resolve();
    assert.equal(modal.open, false);
    assert.deepEqual(focused, ["opener"]);
});
