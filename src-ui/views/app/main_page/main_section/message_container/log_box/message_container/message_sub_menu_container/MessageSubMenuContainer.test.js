import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, eventTarget, stubGlobals } from "../../../../../../../../logics/test/hookHarness.js";

const setup = async context => {
    const runtime = hooks(), window = eventTarget(), timers = new Map(), sent = [], edited = [], hovered = [];
    let timerId = 0;
    context.after(() => runtime.unmount());
    stubGlobals(context, { window, setTimeout: (fn, delay) => {
        assert.equal(delay, 500);
        timers.set(++timerId, fn);
        return timerId;
    }, clearTimeout: id => timers.delete(id) });
    const { MessageSubMenuContainer } = await loadModule(new URL("./MessageSubMenuContainer.jsx", import.meta.url), runtime, {
        "@common_components": { Tooltip: () => null },
    });
    const props = { is_shown: true, resendFunction: () => sent.push("resend"), editFunction: () => edited.push("edit"),
        setIsHovered: value => hovered.push(value) };
    const render = () => find(runtime.render(MessageSubMenuContainer, props), node => node.type === "button");
    const captured = new Set(), target = { setPointerCapture: id => captured.add(id),
        hasPointerCapture: id => captured.has(id), releasePointerCapture: id => captured.delete(id),
        getBoundingClientRect: () => ({ left: 0, right: 100, top: 0, bottom: 50 }) };
    const down = (button = 0, isPrimary = true) => {
        const control = render();
        (control.props.onPointerDown ?? control.props.onMouseDown)({ button, isPrimary, pointerId: 1, currentTarget: target });
    };
    return { runtime, window, timers, sent, edited, hovered, render, down, captured };
};

test("resend accepts only a primary pointer hold; a click still edits", async context => {
    const s = await setup(context);
    for (const [button, primary] of [[1, true], [2, true], [0, false]]) {
        s.down(button, primary);
        for (const fn of [...s.timers.values()]) fn();
        assert.deepEqual(s.sent, []);
        assert.equal(s.timers.size, 0);
    }
    s.render().props.onClick();
    assert.deepEqual(s.edited, ["edit"]);
    s.down();
    const complete = [...s.timers.values()][0];
    complete();
    complete();
    assert.deepEqual(s.sent, ["resend"]);
    assert.deepEqual(s.hovered, [false]);
    assert.equal(s.timers.size, 0);
    assert.equal(s.captured.size, 0);
});

for (const cancel of ["onPointerUp", "onPointerLeave", "onPointerCancel", "onLostPointerCapture", "onBlur", "window blur", "unmount"])
    test(`resend ${cancel} invalidates the hold, including a queued timer callback`, async context => {
        const s = await setup(context);
        s.down();
        const stale = [...s.timers.values()][0];
        if (cancel === "unmount") s.runtime.unmount();
        else if (cancel === "window blur") s.window.dispatch("blur");
        else {
            const oldName = { onPointerUp: "onMouseUp", onPointerLeave: "onMouseLeave" }[cancel];
            const props = s.render().props;
            (props[cancel] ?? props[oldName])?.({ pointerId: 1 });
        }
        assert.equal(s.timers.size, 0);
        stale();
        assert.deepEqual(s.sent, []);
        assert.equal(s.captured.size, 0);
        if (cancel !== "unmount") {
            s.down();
            const current = [...s.timers.values()][0];
            stale();
            assert.deepEqual(s.sent, []);
            current();
            assert.deepEqual(s.sent, ["resend"]);
        }
        s.runtime.unmount();
        assert.deepEqual(s.window.removed, s.window.added);
    });

test("duplicate pointerdown cannot orphan the first hold timer", async context => {
    const s = await setup(context);
    s.down();
    const first = [...s.timers.values()][0];
    s.down();
    assert.equal(s.timers.size, 1);
    s.runtime.unmount();
    first();
    assert.deepEqual(s.sent, []);
});

test("moving a captured pointer outside the resend button cancels the hold", async context => {
    const s = await setup(context);
    s.down();
    const stale = [...s.timers.values()][0];
    s.render().props.onPointerMove({ pointerId: 1, clientX: 50, clientY: 25 });
    assert.equal(s.timers.size, 1);
    s.render().props.onPointerMove({ pointerId: 1, clientX: 101, clientY: 25 });
    assert.equal(s.timers.size, 0);
    stale();
    assert.deepEqual(s.sent, []);
});
