import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../logics/test/hookHarness.js";

async function setup(context) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const controls = hooks(), parent = hooks(), writes = [];
    let active = parent;
    const bindings = { ...controls, api: { ...controls.api,
        useState: initial => active.api.useState(initial),
        useRef: initial => active.api.useRef(initial),
    } };
    context.after(() => controls.unmount());
    const saved = { tracker: "HMD", x_pos: 0, y_pos: 0 };
    const { Vr } = await loadModule(new URL("./Vr.jsx", import.meta.url), bindings, {
        "@ui_configs": { ui_configs: {} }, "../_components": { Slider: "slider", SectionLabelComponent: "section" },
        "../_templates/Templates": { RadioButtonContainer: "radio", CheckboxContainer: "checkbox", ActionButtonContainer: "action" },
        "@common_components": { ResetButton: "reset" }, "@utils": {},
        "@logics_configs": { useVr: () => ({ currentOverlaySmallLogSettings: { data: saved, state: "ok" } }) },
    });
    const node = find(parent.render(Vr), item => item.type?.name === "OverlaySettingsContainer");
    active = controls;
    const target = node.type;
    const props = { ...node.props, default_ui_configs: saved, setOverlaySettings: value => { writes.push(value); return true; } };
    const render = () => { controls.render(target, props); return controls.render(target, props); };
    const handlers = () => find(render(), item => item.props?.selectFunction && item.props?.onChangeFunction).props;
    return { props, handlers, writes, unmount: controls.unmount };
}

for (const reset of [false, true]) test(`VR pending position write preserves the newer ${reset ? "axis reset" : "tracker selection"}`, async context => {
    const s = await setup(context);
    s.handlers().onChangeFunction("x_pos", 0.1);
    context.mock.timers.tick(10);
    s.handlers().selectFunction(reset ? "x_pos" : "tracker", reset ? 0 : "LeftHand");
    context.mock.timers.tick(300);
    assert.equal(s.writes.at(-1).tracker, reset ? "HMD" : "LeftHand");
    assert.equal(s.writes.at(-1).x_pos, reset ? 0 : 0.1);
    assert.equal(s.writes.length, 1);
    s.handlers().onChangeFunction("y_pos", 0.2);
    context.mock.timers.tick(50);
    assert.equal(s.writes.at(-1).tracker, reset ? "HMD" : "LeftHand");
    assert.equal(s.writes.at(-1).y_pos, 0.2);
});

test("VR editor cancels delayed writes on unmount", async context => {
    const s = await setup(context);
    s.handlers().onChangeFunction("x_pos", 0.1);
    s.unmount(); context.mock.timers.tick(300);
    assert.deepEqual(s.writes, []);
});

test("an older VR save response cannot replace the latest tracker draft", async context => {
    const s = await setup(context), requests = [];
    s.props.setOverlaySettings = value => new Promise(resolve => requests.push({ value, resolve }));
    s.handlers().onChangeFunction("x_pos", 0.1);
    context.mock.timers.tick(50);
    s.props.state = "pending";
    s.handlers().selectFunction("tracker", "LeftHand");
    s.props.current_overlay_settings = requests[0].value;
    s.props.state = "ok";
    s.handlers();
    requests[0].resolve({ status: 200, result: requests[0].value });
    await Promise.resolve();
    assert.equal(s.handlers().settings.tracker, "LeftHand");
    requests[1].resolve({ status: 200, result: requests[1].value });
    await Promise.resolve();
    assert.equal(s.handlers().settings.tracker, "LeftHand");
});

test("restoring all VR defaults cancels the editor's pending position write", async context => {
    const s = await setup(context);
    s.handlers().onChangeFunction("x_pos", 0.1);
    s.props.resetRef.current();
    context.mock.timers.tick(300);
    assert.deepEqual(s.writes, []);
    assert.equal(s.handlers().settings.x_pos, 0);
});
