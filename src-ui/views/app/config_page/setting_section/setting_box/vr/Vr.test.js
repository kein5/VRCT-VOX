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
        "@logics_common": { useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: true } }) },
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

test("closing settings stops the overlay sample text, and reopening does not restart it", async context => {
    context.mock.timers.enable({ apis: ["setInterval"] });
    // The settings page stays mounted while closed, so the button sees the
    // closed state instead of unmounting.
    const runtimes = { vr: hooks(), overlay: hooks(), button: hooks() }, sent = [];
    let active = runtimes.vr, open = true;
    const delegate = name => (...args) => active.api[name](...args);
    const api = { ...runtimes.button.api };
    for (const name of ["useState", "useRef", "useEffect", "useLayoutEffect", "useMemo", "useCallback", "useId"]) api[name] = delegate(name);
    context.after(() => Object.values(runtimes).forEach(runtime => runtime.unmount()));
    const saved = { tracker: "HMD" };
    const { Vr } = await loadModule(new URL("./Vr.jsx", import.meta.url), { ...runtimes.button, api }, {
        "@ui_configs": { ui_configs: {} }, "../_components": { Slider: "slider", SectionLabelComponent: "section" },
        "../_templates/Templates": { RadioButtonContainer: "radio", CheckboxContainer: "checkbox", ActionButtonContainer: "action" },
        "@common_components": { ResetButton: "reset" }, "@utils": { randomIntMinMax: () => 1 },
        "@logics_configs": { useVr: () => ({ currentOverlaySmallLogSettings: { data: saved, state: "ok" },
            sendTextToOverlay: text => sent.push(text) }) },
        "@logics_common": { useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: open } }) },
    });
    const overlay = find(runtimes.vr.render(Vr), item => item.type?.name === "OverlaySettingsContainer");
    active = runtimes.overlay;
    const sample = find(runtimes.overlay.render(overlay.type, overlay.props), item => item.type?.name === "SendSampleTextToggleButton");
    active = runtimes.button;
    const button = () => find(runtimes.button.render(sample.type, {}), item => item.type === "button");

    button().props.onClick();
    button();
    context.mock.timers.tick(2000);
    assert.equal(sent.length, 2);

    open = false;
    button();
    context.mock.timers.tick(5000);
    assert.equal(sent.length, 2);

    open = true;
    assert.equal(button().props["aria-label"], "config_page.vr.sample_text_button.start");
    context.mock.timers.tick(5000);
    assert.equal(sent.length, 2);
});

test("restoring all VR defaults cancels the editor's pending position write", async context => {
    const s = await setup(context);
    s.handlers().onChangeFunction("x_pos", 0.1);
    s.props.resetRef.current();
    context.mock.timers.tick(300);
    assert.deepEqual(s.writes, []);
    assert.equal(s.handlers().settings.x_pos, 0);
});
