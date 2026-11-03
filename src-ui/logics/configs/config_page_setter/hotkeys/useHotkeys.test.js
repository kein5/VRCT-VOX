import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup() {
    // Execute the production hook as ESM. Only React, atoms and native APIs are
    // replaced; no plugin, portal, browser or application is started.
    const dependencies = moduleUrl(`
        export const state = { ready: true, settings: false, updating: false, actions: [], notices: [],
            calls: [], handlers: new Set(), removals: 0, cleanups: [], disposers: [],
            hotkeys: { open_quick_chat: ['Ctrl', 'Q'] } };
        export const hot = { data: {}, dispose: callback => state.disposers.push(callback) };
        export const useRef = value => ({ current: value });
        export const useEffect = callback => state.cleanups.push(callback());
        export const store = { appWindow: {} };
        export const Atom_IsOpenedConfigPage = 'settings', Atom_IsBackendReady = 'ready', Atom_IsSoftwareUpdating = 'updating';
        export const getDefaultStore = () => ({ get: atom => ({ data: state[atom] }) });
        export const useStore_Hotkeys = () => ({ currentHotkeys: { data: state.hotkeys }, updateHotkeys() {}, pendingHotkeys() {} });
        export const useStdoutToPython = () => ({ asyncStdoutToPython: async () => true });
        export const useNotificationStatus = () => ({ showNotification_SaveSuccess() {}, closeNotification() {},
            showNotification_Error: (...args) => state.notices.push(args) });
        export const useI18n = () => ({ t: key => key, i18n: { exists: () => true } });
        export const useMainFunction = () => ({ toggleTranslation: () => state.actions.push('translation'),
            toggleTranscriptionSend: () => state.actions.push('send'), toggleTranscriptionReceive: () => state.actions.push('receive') });
        export const invoke = async (command, args) => {
            state.calls.push([command, args]);
            if (command === 'quick_chat_shortcut_platform') return state.platformGate ?? 'wayland';
            if (command === 'portal_shortcuts_bind') return state.bind?.(args) ?? {};
            if (command === 'quick_chat_show') state.actions.push('quick-chat');
        };
        export const listen = async (name, callback) => {
            state.handlers.add(callback);
            await state.listenGate;
            return () => { state.handlers.delete(callback); state.removals++; };
        };
        export const register = async () => {};
        export const unregister = async () => {};
        export const unregisterAll = async () => { await state.unregisterGate; };
    `) + `#${crypto.randomUUID()}`;
    const { state, hot } = await import(dependencies);
    let instance = 0;
    const load = async () => {
        let source = await readFile(new URL("./useHotkeys.js", import.meta.url), "utf8");
        source = source.replace(/from "[^"]+"/g, `from ${JSON.stringify(dependencies)}`);
        source = `import { hot } from ${JSON.stringify(dependencies)};\n` + source.replaceAll("import.meta.hot", "hot");
        const module = await import(moduleUrl(source) + `#${instance++}`);
        return module.useHotkeys();
    };
    return { state, load, dispose: index => state.disposers[index](hot.data),
        emit: () => { for (const callback of state.handlers) callback({ payload: { id: "open_quick_chat" } }); } };
}

for (const boundary of ["platform", "unregister", "listen", "bind"]) {
    test(`pause during ${boundary} await prevents a late registration from enabling shortcuts`, async () => {
        const subject = await setup(), gate = deferred();
        const { state } = subject;
        if (boundary === "bind") state.bind = () => gate.promise;
        else state[`${boundary}Gate`] = gate.promise;
        const hook = await subject.load();
        const registration = hook.registerShortcuts();
        await flush();
        // Explicit pause invalidates this registration even if no atom changed.
        const pause = hook.unregisterAll();
        gate.resolve(boundary === "platform" ? "wayland" : {});
        await Promise.all([registration, pause]);
        subject.emit();
        assert.deepEqual(state.actions, []);
        if (boundary !== "bind") assert.equal(state.calls.filter(([cmd]) => cmd === "portal_shortcuts_bind").length, 0);
    });
}

for (const [atom, value] of [["settings", true], ["ready", false], ["updating", true]]) {
    test(`current ${atom} state is rechecked after bind without waiting for controller effects`, async () => {
        const subject = await setup(), gate = deferred();
        subject.state.bind = () => gate.promise;
        const hook = await subject.load(), registration = hook.registerShortcuts();
        await flush();
        subject.state[atom] = value;
        gate.resolve({});
        await registration;
        subject.emit();
        assert.deepEqual(subject.state.actions, []);
    });
}

test("unmount removes the handler and late bind cannot dispatch or report a stale error", async () => {
    const subject = await setup(), gate = deferred();
    subject.state.bind = () => gate.promise;
    const hook = await subject.load(), registration = hook.registerShortcuts();
    await flush();
    subject.state.cleanups[0]();
    assert.equal(subject.state.handlers.size, 0);
    gate.reject("portal_cancelled");
    await registration;
    subject.emit();
    assert.deepEqual(subject.state.actions, []);
    assert.deepEqual(subject.state.notices, []);
    assert.equal(subject.state.removals, 1);
});

test("unmount before listen resolves still calls the eventual unlisten", async () => {
    const subject = await setup(), gate = deferred();
    subject.state.listenGate = gate.promise;
    const hook = await subject.load(), registration = hook.registerShortcuts();
    await flush();
    subject.state.cleanups[0]();
    subject.emit();
    assert.deepEqual(subject.state.actions, []);
    gate.resolve();
    await registration;
    assert.equal(subject.state.handlers.size, 0);
    assert.equal(subject.state.removals, 1);
    assert.equal(subject.state.calls.filter(([cmd]) => cmd === "portal_shortcuts_bind").length, 0);
});

test("two module instances dispatch only once after HMR disposal", async () => {
    const subject = await setup();
    const first = await subject.load();
    await first.registerShortcuts();
    subject.dispose(0);
    const second = await subject.load();
    await second.registerShortcuts();
    subject.emit();
    assert.deepEqual(subject.state.actions, ["quick-chat"]);
    assert.equal(subject.state.handlers.size, 1);
    assert.equal(subject.state.removals, 1);
    // Old component cleanup must not remove the new module's listener.
    subject.state.cleanups[0]();
    assert.equal(subject.state.handlers.size, 1);
});

test("HMR disposes a pending listen without removing the replacement handler", async () => {
    const subject = await setup(), gate = deferred();
    subject.state.listenGate = gate.promise;
    const first = await subject.load(), registration = first.registerShortcuts();
    await flush();
    subject.dispose(0);
    subject.state.listenGate = null;
    const second = await subject.load();
    await second.registerShortcuts();
    gate.resolve();
    await registration;
    subject.emit();
    assert.deepEqual(subject.state.actions, ["quick-chat"]);
    assert.equal(subject.state.handlers.size, 1);
});

test("newer registration wins when old completion arrives last", async () => {
    const subject = await setup(), old = deferred();
    subject.state.bind = () => old.promise;
    const hook = await subject.load(), registration = hook.registerShortcuts();
    await flush();
    await hook.unregisterAll();
    subject.state.bind = () => ({});
    await hook.registerShortcuts();
    old.resolve({ open_quick_chat: { applied: false, shown: "old" } });
    await registration;
    subject.emit();
    assert.deepEqual(subject.state.actions, ["quick-chat"]);
    assert.deepEqual(subject.state.notices, []);
});

test("failed listen can be retried deliberately", async () => {
    const subject = await setup();
    subject.state.listenGate = Promise.reject("portal_unavailable");
    // Observe the fake rejection before the hook gets to the listener await.
    subject.state.listenGate.catch(() => {});
    const hook = await subject.load();
    await hook.registerShortcuts();
    subject.state.listenGate = null;
    await hook.registerShortcuts();
    subject.emit();
    assert.deepEqual(subject.state.actions, ["quick-chat"]);
});

test("VR window command checks the injected calling window before any mutation or await", async () => {
    const source = await readFile(new URL("../../../../../src-tauri/src/lib.rs", import.meta.url), "utf8");
    const command = source.slice(source.indexOf("async fn set_vr_panel_window("), source.indexOf("use font_kit"));
    assert.match(command, /window: tauri::WebviewWindow/);
    assert.match(command, /\{\s*if window\.label\(\) != "main" \{\s*return Err\("vr_panel_forbidden"\.into\(\)\);\s*\}\s*let _guard = VR_PANEL_LOCK\.lock\(\)\.await;/);
});
