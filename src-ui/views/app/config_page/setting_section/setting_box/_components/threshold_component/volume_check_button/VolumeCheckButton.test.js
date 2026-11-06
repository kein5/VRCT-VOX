import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../../../logics/test/hookHarness.js";

test("holding Enter or Space toggles the volume check once, and a pending check ignores presses", async () => {
    const runtime = hooks(), calls = [];
    const { VolumeCheckButton } = await loadModule(new URL("./VolumeCheckButton.jsx", import.meta.url), runtime);
    const props = { isChecking: { state: "ok", data: false }, SvgComponent: () => null,
        startFunction: () => calls.push("start"), stopFunction: () => calls.push("stop") };
    const button = () => find(runtime.render(VolumeCheckButton.type, props), node => node.props?.role === "button");
    const press = (key, repeat = false) => button().props.onKeyDown({ key, repeat, preventDefault() {} });

    press("Enter");
    for (let i = 0; i < 5; i++) press("Enter", true);
    assert.deepEqual(calls, ["start"]);

    props.isChecking = { state: "pending", data: false };
    assert.equal(button().props["aria-disabled"], true);
    press("Enter");
    button().props.onClick();
    assert.deepEqual(calls, ["start"]);

    props.isChecking = { state: "ok", data: true };
    assert.equal(button().props["aria-disabled"], false);
    press(" ");
    for (let i = 0; i < 5; i++) press(" ", true);
    assert.deepEqual(calls, ["start", "stop"]);
});
