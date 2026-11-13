import assert from "node:assert/strict";
import { test } from "node:test";
import { eventTarget, stubGlobals } from "../../logics/test/hookHarness.js";
import { trackVrPointerHover } from "./vrPanelHover.js";

function setup(context) {
    let hover;
    context.after(() => hover?.dispose());
    const frames = new Map(), observers = [], hits = [], writes = [];
    let sequence = 0, hit = null;
    const root = { ...eventTarget(), contains: target => !target.outside, querySelectorAll: () => ["panel", "popup"] };
    context.mock.method(root, "addEventListener");
    const window = eventTarget(), fonts = eventTarget();
    const document = { fonts, documentElement: {}, body: {}, elementFromPoint: (x, y) => { hits.push([x, y]); return hit; } };
    class Observer {
        constructor(callback) { this.callback = callback; this.observed = []; observers.push(this); }
        observe(...args) { this.observed.push(args); }
        disconnect() { this.disconnected = true; }
    }
    stubGlobals(context, { window, document, MutationObserver: Observer, ResizeObserver: Observer,
        requestAnimationFrame: fn => { frames.set(++sequence, fn); return sequence; },
        cancelAnimationFrame: id => frames.delete(id),
    });
    hover = trackVrPointerHover(root);
    const button = name => ({
        closest(selector) { return selector === "[inert]" ? (this.inert ? this : null) : this; },
        setAttribute: (...args) => writes.push([name, "set", ...args]),
        removeAttribute: (...args) => writes.push([name, "remove", ...args]),
    });
    return { hover, root, window, fonts, frames, observers, hits, writes, button,
        setHit: value => { hit = value; },
        frame: () => { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn()); },
    };
}

test("scroll under a stationary pointer re-hit-tests once per frame, with no unchanged-target writes", context => {
    const s = setup(context), first = s.button("first"), second = s.button("second");
    assert.equal(s.root.addEventListener.mock.calls[0].arguments[2], true);
    s.setHit(first);
    for (let i = 0; i < 100; i++) s.hover.setPointer({ x: 10, y: 20 });
    assert.equal(s.frames.size, 1);
    s.frame();
    assert.deepEqual(s.hits, [[10, 20]]);
    assert.equal(s.writes.length, 1);
    for (let i = 0; i < 100; i++) s.root.dispatch("scroll");
    s.frame();
    assert.equal(s.hits.length, 2);
    assert.equal(s.writes.length, 1);
    s.setHit(second);
    for (let i = 0; i < 100; i++) s.root.dispatch("scroll");
    s.frame();
    assert.equal(s.hits.length, 3);
    assert.deepEqual(s.writes.slice(1), [["first", "remove", "data-vr-hover"], ["second", "set", "data-vr-hover", ""]]);
    assert.equal(s.frames.size, 0);
});

test("view, layout, font and window changes share the scroll frame and use the latest coordinates", context => {
    const s = setup(context);
    s.setHit(s.button("picker"));
    s.hover.setPointer({ x: 1, y: 2 });
    s.hover.setPointer({ x: 3, y: 4 });
    s.observers.forEach(observer => observer.callback());
    s.window.dispatch("resize");
    s.fonts.dispatch("loadingdone");
    s.root.dispatch("scroll");
    assert.equal(s.frames.size, 1);
    s.frame();
    assert.deepEqual(s.hits, [[3, 4]]);
    const mutations = s.observers[0].observed[0][1];
    assert.equal(mutations.subtree, true);
    assert.equal(mutations.childList, true);
    assert.equal(mutations.attributeFilter.includes("data-vr-hover"), false);
    assert.equal(s.observers[0].observed.length, 3); // Atlas plus inherited html/body styles.
    assert.equal(s.observers[1].observed.length, 3);
});

test("null pointer and teardown cancel queued tests and clear hover; inert targets stay clear", context => {
    const s = setup(context), button = s.button("button");
    s.setHit(button);
    s.hover.setPointer({ x: 1, y: 2 });
    s.frame();
    s.root.dispatch("scroll");
    s.hover.setPointer(null);
    assert.equal(s.frames.size, 0);
    assert.equal(s.writes.at(-1)[1], "remove");
    s.root.dispatch("scroll");
    assert.equal(s.frames.size, 0);
    button.inert = true;
    s.hover.setPointer({ x: 1, y: 2 });
    s.frame();
    assert.equal(s.writes.length, 2);
    s.root.dispatch("scroll");
    s.hover.dispose();
    s.hover.setPointer({ x: 3, y: 4 }); // A late Tauri callback cannot revive it.
    s.root.dispatch("scroll");
    s.frame();
    assert.equal(s.hits.length, 2);
    assert.ok(s.observers.every(observer => observer.disconnected));
    assert.equal(s.root.removed.length, 1);
});
