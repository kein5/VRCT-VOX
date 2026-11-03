import assert from "node:assert/strict";
import { test } from "node:test";
import { createSidecarSessionOwner } from "./sidecarSession.js";
import { expectBackendExit } from "./sidecarExitExpectation.js";
import { loadModule, find } from "../test/hookHarness.js";
import { deferred, flush, loadBridgeStore } from "../test/bridgeHarness.js";
import * as utils from "../utils.js";

const setup = () => {
    const store = {}, attempts = [], timers = new Map(), states = [], messages = [], crashes = [];
    let timerId = 0, stops = 0, feeds = 0;
    const createCommand = () => {
        const spawn = deferred(), events = {}, stdout = {}, stderr = {};
        const child = { kills: 0, kill: async () => { child.kills++; } };
        const command = { on: (name, fn) => { events[name] = fn; },
            stdout: { on: (name, fn) => { stdout[name] = fn; } },
            stderr: { on: (name, fn) => { stderr[name] = fn; } }, spawn: () => spawn.promise };
        attempts.push({ command, spawn, child, events, stdout, stderr });
        return command;
    };
    const timerTools = {
        setInterval: (fn, delay) => { assert.equal(delay, 20000); timers.set(++timerId, fn); return timerId; },
        clearInterval: id => timers.delete(id),
    };
    const owner = createSidecarSessionOwner({ store, createCommand, ...timerTools });
    const handlers = { setStartupState: phase => states.push(phase), beginStartup: () => {}, started: () => {},
        receiveRoutes: value => messages.push(value), backendStopped: () => { stops++; },
        unexpectedExit: event => crashes.push(event), stderr: line => messages.push(line), feedWatchdog: () => { feeds++; } };
    return { store, attempts, timers, states, messages, crashes, owner, handlers, createCommand, timerTools,
        mount: () => owner.attach(() => handlers), get stops() { return stops; }, get feeds() { return feeds; }, get installations() { return timerId; } };
};

test("two mounts share a pending/live session; detach and StrictMode replay keep one watchdog", async () => {
    const s = setup(), detachA = s.mount(), detachB = s.mount();
    await flush();
    assert.equal(s.attempts.length, 1);
    s.attempts[0].spawn.resolve(s.attempts[0].child);
    await s.store.backend_session.completion;
    assert.equal(s.timers.size, 1);
    detachA();
    assert.equal(s.timers.size, 1);
    detachB();
    assert.equal(s.timers.size, 0);
    const detachReplay = s.mount();
    assert.equal(s.attempts.length, 1);
    assert.equal(s.timers.size, 1);
    s.timers.values().next().value();
    assert.equal(s.feeds, 1);
    detachReplay();
});

test("unmount before spawn resolves installs no late watchdog; remount resumes feeding", async () => {
    const s = setup(), detach = s.mount();
    await flush();
    detach();
    s.attempts[0].spawn.resolve(s.attempts[0].child);
    await s.store.backend_session.completion;
    assert.equal(s.installations, 0);
    const detachAgain = s.mount();
    assert.equal(s.timers.size, 1);
    assert.equal(s.attempts.length, 1);
    detachAgain();
});

test("failed spawn has no automatic retry; repeated retry clicks start one new attempt", async context => {
    context.mock.method(console, "error", () => {});
    const s = setup(), detach = s.mount();
    await flush();
    s.attempts[0].spawn.reject(Error("missing executable"));
    await s.store.backend_session.completion;
    assert.equal(s.states.at(-1), "failed");
    assert.equal(s.store.backend_stopped, true);
    assert.equal(s.store.backend_subprocess, null);
    assert.equal(s.installations, 0);
    detach();
    const detachAgain = s.mount();
    assert.equal(s.states.at(-1), "failed");
    assert.equal(s.attempts.length, 1);
    const retry = s.owner.retry();
    assert.equal(s.states.at(-1), "starting");
    assert.equal(await s.owner.retry(), false);
    await flush();
    assert.equal(s.attempts.length, 2);
    s.attempts[1].spawn.resolve(s.attempts[1].child);
    await retry;
    assert.equal(s.store.backend_subprocess, s.attempts[1].child);
    assert.equal(s.timers.size, 1);
    detachAgain();
});

test("command error retires a late child before retry; stale events cannot affect the replacement", async context => {
    context.mock.method(console, "error", () => {});
    const s = setup(), detach = s.mount();
    await flush();
    const a = s.attempts[0], kill = deferred();
    a.child.kill = () => { a.child.kills++; return kill.promise; };
    a.events.error("failed pipe");
    assert.equal(s.states.at(-1), "failed");
    const retry = s.owner.retry();
    a.spawn.resolve(a.child);
    await flush();
    assert.equal(s.attempts.length, 1);
    assert.equal(a.child.kills, 1);
    kill.resolve();
    await flush();
    assert.equal(s.attempts.length, 2);
    const b = s.attempts[1];
    b.spawn.resolve(b.child);
    await retry;
    const installations = s.installations, stops = s.stops;
    a.events.close({ code: 1 });
    a.events.error("late error");
    a.stdout.data('{"endpoint":"old"}');
    a.stderr.data("late stderr");
    assert.equal(s.store.backend_subprocess, b.child);
    assert.equal(s.store.backend_stopped, false);
    assert.equal(s.stops, stops);
    assert.equal(s.installations, installations);
    assert.equal(s.timers.size, 1);
    assert.deepEqual(s.messages, []);
    b.stdout.data('{"endpoint":"new"}');
    assert.deepEqual(s.messages, [{ endpoint: "new" }]);
    detach();
});

test("failed cleanup prevents replacement until the child can be retired", async context => {
    context.mock.method(console, "error", () => {});
    const s = setup(), detach = s.mount();
    await flush();
    const a = s.attempts[0];
    a.child.kill = async () => { throw Error("kill failed"); };
    a.events.error("spawn failed");
    a.spawn.resolve(a.child);
    await s.store.backend_session.completion;
    assert.equal(await s.owner.retry(), false);
    assert.equal(s.attempts.length, 1);
    assert.equal(s.states.at(-1), "failed");
    a.events.close({ code: 1 });
    const retry = s.owner.retry();
    await flush();
    s.attempts[1].spawn.resolve(s.attempts[1].child);
    await retry;
    detach();
});

test("a command error while running is logged and keeps the live sidecar", async context => {
    const logged = context.mock.method(console, "error", () => {});
    const s = setup(), detach = s.mount();
    await flush();
    const a = s.attempts[0];
    a.spawn.resolve(a.child);
    await s.store.backend_session.completion;
    a.events.error("stderr read failed");
    assert.equal(s.store.backend_subprocess, a.child);
    assert.equal(s.store.backend_stopped, false);
    assert.equal(a.child.kills, 0);
    assert.equal(s.states.at(-1), "running");
    assert.equal(logged.mock.callCount(), 1);
    a.stdout.data('{"endpoint":"still-live"}');
    assert.deepEqual(s.messages, [{ endpoint: "still-live" }]);
    detach();
});

test("expected exits release pending state without a crash notice and do not survive sessions", async () => {
    const s = setup(), detach = s.mount();
    await flush();
    s.attempts[0].spawn.resolve(s.attempts[0].child);
    await s.store.backend_session.completion;
    expectBackendExit(s.store.backend_session, "/run/update_cuda_software");
    s.attempts[0].events.close({ code: 0 });
    assert.equal(s.stops, 1);
    assert.deepEqual(s.crashes, []);
    assert.equal(s.store.backend_session.expectedExits.size, 0);
    assert.equal(s.timers.size, 0);
    detach();
});

test("production controller publishes startup failure and the persistent screen offers a working retry", async context => {
    context.mock.method(console, "error", () => {});
    const s = setup(), b = await loadBridgeStore();
    context.mock.method(globalThis, "setInterval", s.timerTools.setInterval);
    context.mock.method(globalThis, "clearInterval", s.timerTools.clearInterval);
    const common = { useNotificationStatus: () => ({ showNotification_Error: () => {} }),
        useIsBackendReady: b.stores.useStore_IsBackendReady, useWindow: () => ({ asyncCloseApp: () => {} }) };
    const module = await loadModule(new URL("../../views/app/_app_controllers/StartPythonController.jsx", import.meta.url), b.runtime, {
        "@tauri-apps/api/core": { invoke: async () => [] },
        "@tauri-apps/plugin-shell": { Command: { sidecar: s.createCommand } },
        "@store": b.stores, "@utils": utils, "@logics_common": common,
        "@useReceiveRoutes": { useReceiveRoutes: () => ({ receiveRoutes: () => {}, backendStopped: () => {} }) },
        "../../../logics/common/sidecarSession.js": { createSidecarSessionOwner },
    });
    b.runtime.render(module.StartPythonController);
    await flush();
    s.attempts[0].spawn.reject(Error("not found"));
    await b.stores.store.backend_session.completion;
    assert.equal(b.runtime.store.get(b.stores.Atom_BackendStartupState).data, "failed");
    assert.equal(b.runtime.store.get(b.stores.Atom_IsBackendReady).data, false);
    const startup = await loadModule(new URL("./useBackendStartup.js", import.meta.url), b.runtime, { "@store": b.stores });
    const screen = await loadModule(new URL("../../views/app/others/splash_component/StartupFailedComponent.jsx", import.meta.url), b.runtime, {
        "@logics_common": common, "@common_components": { CloseButton: () => null },
        "../../../../logics/common/useBackendStartup": startup,
    });
    const tree = screen.StartupFailedComponent();
    assert.ok(find(tree, node => node.props.role === "alert"));
    assert.ok(find(tree, node => node.props.children === "common_error.backend_startup_failed"));
    const button = find(tree, node => node.type === "button");
    assert.equal(button.props.children, "common_error.backend_startup_retry");
    const retry = button.props.onClick();
    button.props.onClick();
    await flush();
    assert.equal(s.attempts.length, 2);
    assert.equal(b.runtime.store.get(b.stores.Atom_BackendStartupState).data, "starting");
    s.attempts[1].spawn.resolve(s.attempts[1].child);
    await retry;
    b.runtime.unmount();
    assert.equal(s.timers.size, 0);
});
