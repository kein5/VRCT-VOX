import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { hooks, loadModule, find, stubGlobals } from "../../../../logics/test/hookHarness.js";

const EnvReadout = () => null;
async function setup(context, { presence = null, sends = true } = {}) {
    const runtime = hooks(), asked = [], timers = [];
    const state = { presence, sends };
    stubGlobals(context, { setInterval: (fn, ms) => { timers.push({ fn, ms, cleared: false }); return timers.length - 1; },
        clearInterval: id => { timers[id].cleared = true; } });
    const { VrchatPresence } = await loadModule(new URL("./VrchatPresence.jsx", import.meta.url), runtime, {
        "@logics_configs": { useOthers: () => ({ currentVrchatOscPresence: { data: state.presence },
            currentEnableSendMessageToVrc: { data: state.sends }, getVrchatOscPresence: () => asked.push(true) }) },
        "../../config_page/setting_section/setting_box/_components/env_readout/EnvReadout": { EnvReadout },
    });
    const draw = () => {
        const readout = runtime.render(VrchatPresence, { className: "placed" });
        const lines = []; find(readout, node => { if (node.type === "p") lines.push(node.props.children); return false; });
        return { tone: readout.props.tone ?? "neutral", lines, className: readout.props.className };
    };
    return { draw, asked, timers, state, unmount: () => runtime.unmount() };
}

test("it says in words whether a VRChat with OSC enabled is on this PC, and how to turn OSC on when it is not", async context => {
    const s = await setup(context);
    assert.deepEqual(s.draw(), { tone: "neutral", lines: ["vrchat_presence.checking"], className: "placed" });
    s.state.presence = "found";
    assert.deepEqual(s.draw(), { tone: "active", lines: ["vrchat_presence.found"], className: "placed" });
    s.state.presence = "not_found";
    assert.deepEqual(s.draw(), { tone: "warning", lines: ["vrchat_presence.not_found", "vrchat_presence.not_found_hint"], className: "placed" });
    s.state.presence = "unknown";
    assert.deepEqual(s.draw(), { tone: "neutral", lines: ["vrchat_presence.unknown"], className: "placed" });
    s.state.presence = { anything: "else" };
    assert.deepEqual(s.draw().lines, ["vrchat_presence.checking"]);
});

test("it asks when shown and every five seconds while on screen, and stops when it leaves", async context => {
    const s = await setup(context);
    s.draw();
    assert.equal(s.asked.length, 1);
    assert.equal(s.timers.length, 1);
    assert.equal(s.timers[0].ms, 5000);
    s.timers[0].fn(); s.timers[0].fn();
    assert.equal(s.asked.length, 3);
    s.draw(); s.draw();
    assert.equal(s.timers.length, 1, "redrawing does not start another timer");
    s.unmount();
    assert.equal(s.timers[0].cleared, true);
});

test("with sending to VRChat off it says so and does not look for VRChat", async context => {
    const s = await setup(context, { sends: false, presence: "not_found" });
    assert.deepEqual(s.draw(), { tone: "neutral", lines: ["vrchat_presence.sending_off"], className: "placed" });
    assert.equal(s.asked.length, 0);
    assert.equal(s.timers.length, 0);
    s.state.sends = true;
    s.draw();
    assert.equal(s.asked.length, 1, "turning sending on starts looking");
});

test("every state has words in English and Japanese", () => {
    for (const language of ["en", "ja"]) {
        const strings = yaml.load(readFileSync(new URL(`../../../../../locales/${language}.yml`, import.meta.url), "utf8")).vrchat_presence;
        for (const key of ["checking", "found", "not_found", "not_found_hint", "unknown", "sending_off"]) assert.equal(typeof strings[key], "string");
    }
});
