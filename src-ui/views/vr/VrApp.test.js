import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals } from "../../logics/test/hookHarness.js";
import * as wire from "../../logics/common/vrPanelWire.js";
import { keepNewestVrLayout } from "../../logics/common/vrPanelTooltip.js";

test("closed log region is inert and unpainted while the receiver keeps its data current", async context => {
    stubGlobals(context, { requestAnimationFrame: () => 1, cancelAnimationFrame: () => {} });
    const runtime = hooks(), listeners = new Map(), atoms = new Map(), subscriptions = [], emitted = [];
    class Channel { onmessage = () => {}; }
    const layout = { atlas: [2000, 1000], regions: { panel: [0, 0, 900, 900] } };
    const VrLogWindow = () => null, VrLauncher = () => null;
    const { VrApp } = await loadModule(new URL("./VrApp.jsx", import.meta.url), runtime, {
        "@tauri-apps/api/core": { Channel, invoke: async (name, args) => { subscriptions.push([name, args.channel]); } },
        "@tauri-apps/api/event": { emit: (...args) => { emitted.push(args); }, listen: (name, handler) => {
            listeners.set(name, handler);
            return Promise.resolve(() => listeners.delete(name));
        } },
        jotai: { getDefaultStore: () => ({ set: (atom, value) => atoms.set(atom,
            typeof value === "function" ? value(atoms.get(atom)) : value) }) },
        "@store": { dynamicStoreRegistry: { Atom_MessageLogs: "logs" } },
        "@logics_common": { useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: false } }) },
        "../app/_app_controllers": { UiLanguageController: () => null, FontFamilyController: () => null },
        "@logics_configs": { useVr: () => ({ currentVrPanelLayout: { data: layout } }) },
        "./VrLauncher": { VrLauncher }, "./VrLogWindow": { VrLogWindow }, "./VrPopupWindow": { VrPopupWindow: () => null },
        "./VrToolbar": { VrToolbar: () => null }, "./VrTooltip": { VrTooltip: () => null }, "./vrPanelHover": {},
        "../../logics/common/vrPanelTooltip": { keepNewestVrLayout }, "../../logics/common/vrPanelWire": wire,
    });
    const closed = runtime.render(VrApp);
    const log = find(closed, node => node.type === VrLogWindow);
    assert.equal(log.props.open, false);
    const region = find(closed, node => node.props.name === "panel");
    const element = region.type(region.props);
    assert.equal(element.props.inert, "");
    assert.equal(element.props["aria-hidden"], true);
    assert.equal(element.props.style.visibility, "hidden");
    const receiver = find(closed, node => node.type?.name === "VrStateReceiver");
    find(closed, node => node.type === VrLauncher).props.openLog();
    const opened = runtime.render(VrApp);
    const openedRegion = find(opened, node => node.props.name === "panel");
    assert.equal(openedRegion.type(openedRegion.props).props.inert, undefined);
    assert.equal(find(opened, node => node.type === VrLogWindow).props.open, true);
    runtime.unmount();
    // Run the receiver's standalone effect, without rendering any log body.
    runtime.api.useEffect = effect => { context.after(effect()); };
    receiver.type();
    // SEC-03: the state arrives on the panel's own channel; the panel asks for it once subscribed.
    assert.equal(listeners.has("vr-panel-state"), false);
    assert.equal(subscriptions.length, 1);
    const [command, channel] = subscriptions[0];
    assert.equal(command, "vr_panel_state_subscribe");
    emitted.length = 0;
    await Promise.resolve();
    assert.deepEqual(emitted.map(([name]) => name), ["vr-panel-ready"]);
    channel.onmessage({ MessageLogs: wire.encodeOrdered({ state: "ok", data: [{ id: "new", status: "pending" }] }) });
    assert.equal(atoms.get("logs").data[0].id, "new");
});
