import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals } from "../../logics/test/hookHarness.js";
import { flush } from "../../logics/test/bridgeHarness.js";
import * as lines from "../../logics/captionOverlay/lines.js";

const findAll = (tree, match, found = []) => {
    if (Array.isArray(tree)) tree.forEach(item => findAll(item, match, found));
    else if (tree && typeof tree === "object") {
        if (match(tree)) found.push(tree);
        findAll(tree.props?.children, match, found);
    }
    return found;
};

async function setup(context, snapshot) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), properties = new Map(), callbacks = {}, removed = [];
    let clock = 1000, current = snapshot, reads = 0;
    stubGlobals(context, { document: { documentElement: { style: { setProperty: (key, value) => properties.set(key, value) } } } });
    const bridge = {
        snapshot: async () => { reads++; return current; },
        onChanged: async callback => { callbacks.changed = callback; return () => removed.push("changed"); },
    };
    const { CaptionOverlay } = await loadModule(new URL("./CaptionOverlay.jsx", import.meta.url), runtime, {
        "../../logics/captionOverlay/bridge": { captionOverlayBridge: bridge },
        "../../logics/captionOverlay/lines": lines,
    });
    const render = () => runtime.render(CaptionOverlay, { bridge, now: () => clock });
    render(); await flush(); render();
    context.after(() => runtime.unmount());
    return { runtime, render, properties, callbacks, removed,
        texts: () => findAll(render(), node => node.type === "p").map(node => node.props.children),
        lineClasses: () => findAll(render(), node => node.type === "div" && node.key !== null && node.key !== undefined).map(node => node.props.className),
        container: () => find(render(), node => node.type === "div"),
        advance: ms => { clock += ms; context.mock.timers.tick(ms); },
        set: next => { current = next; },
        get reads() { return reads; },
    };
}

const base = { position: "bottom", font_size: 32, opacity: 0.5, font_family: "Noto Sans JP" };

test("the overlay reads its captions through the command, draws them and applies the look", async context => {
    const s = await setup(context, { ...base, lines: [
        { id: "a", kind: "sent", text: "こんにちは", translations: ["Hello"], pending: false, until: 7000 },
        { id: "b", kind: "received", text: "", translations: ["やあ"], pending: true, until: 9000 },
    ] });
    assert.deepEqual(s.texts(), ["こんにちは", "Hello", "やあ"]);
    assert.equal(s.properties.get("--caption_font_size"), "32px");
    assert.equal(s.properties.get("--caption_plate"), "0.5");
    assert.equal(s.properties.get("--caption_font_family"), '"Noto Sans JP"');
    assert.doesNotMatch(s.container().props.className, /is_top/);
    const [sent, received] = s.lineClasses();
    assert.match(sent, /sent/); assert.doesNotMatch(sent, /is_pending|is_fading/);
    assert.match(received, /received/); assert.match(received, /is_pending/);
});

test("a line fades and then goes when its time has passed, without a new notice", async context => {
    const s = await setup(context, { ...base, lines: [
        { id: "a", kind: "sent", text: "一つ目", translations: [], pending: false, until: 3000 },
        { id: "b", kind: "sent", text: "二つ目", translations: [], pending: false, until: 6000 },
    ] });
    assert.deepEqual(s.texts(), ["一つ目", "二つ目"]);
    s.advance(2000 - lines.FADE_MS);
    assert.match(s.lineClasses()[0], /is_fading/);
    s.advance(lines.FADE_MS);
    assert.deepEqual(s.texts(), ["二つ目"]);
    s.advance(3000);
    assert.deepEqual(s.texts(), []);
});

test("a notice makes the overlay read again; the notice itself carries nothing", async context => {
    const s = await setup(context, { ...base, lines: [] });
    assert.deepEqual(s.texts(), []);
    s.set({ ...base, position: "top", lines: [{ id: "c", kind: "received", text: "Hello", translations: [], pending: false, until: 9000 }] });
    s.callbacks.changed({ payload: { lines: [{ id: "x", kind: "sent", text: "spoofed", translations: [], until: 9e12 }] } });
    await flush();
    assert.deepEqual(s.texts(), ["Hello"]);
    assert.match(s.container().props.className, /is_top/);
    assert.equal(s.reads, 2);
    s.runtime.unmount();
    await flush();
    assert.deepEqual(s.removed, ["changed"]);
});
