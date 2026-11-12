import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { hooks, loadModule } from "../../../test/hookHarness.js";

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
            registered: new Map(), removed: [], writes: [], calls: [], handlers: new Set(), removals: 0, cleanups: [], disposers: [],
            hotkeys: { open_quick_chat: ['Ctrl', 'Q'] } };
        export const hot = { data: {}, dispose: callback => state.disposers.push(callback) };
        export const useRef = value => state.runtime ? state.runtime.api.useRef(value) : ({ current: value });
        export const useEffect = (callback, deps) => state.runtime ? state.runtime.api.useEffect(callback, deps) : state.cleanups.push(callback());
        export const store = { text_area_ref: { current: { focus: () => state.actions.push('focus-input') } }, appWindow: {
            isMinimized: async () => state.minimized ?? false,
            minimize: async () => { state.actions.push('minimize'); },
            unminimize: async () => { state.actions.push('unminimize'); },
            setFocus: async () => { state.actions.push('set-focus'); },
            onFocusChanged: callback => { state.focusChanged = callback; return () => {}; },
        } };
        export const Atom_IsOpenedConfigPage = 'settings', Atom_IsBackendReady = 'ready', Atom_IsSoftwareUpdating = 'updating', Atom_Hotkeys = 'hotkeys';
        export const getDefaultStore = () => ({ get: atom => ({ data: state[atom] }) });
        export const useStore_Hotkeys = () => ({ currentHotkeys: { data: state.hotkeys }, updateHotkeys: value => { state.hotkeys = value; }, pendingHotkeys() {} });
        export const useStdoutToPython = () => ({ asyncStdoutToPython: async (...args) => { state.writes.push(args); return state.writeGate ?? true; } });
        export const useNotificationStatus = () => ({ showNotification_SaveSuccess() {}, closeNotification() {},
            showNotification_Error: (...args) => state.notices.push(args) });
        export const useI18n = () => ({ t: key => key, i18n: { exists: () => true } });
        export const useMainFunction = () => ({ toggleTranslation: () => state.actions.push('translation'),
            toggleTranscriptionSend: () => state.actions.push('send'), toggleTranscriptionReceive: () => state.actions.push('receive') });
        export const voiceActions = Object.fromEntries(['stop', 'toggleMute', 'toggleTts', 'toggleRvc'].map(name => [name, () => state.actions.push(name)]));
        export const invoke = async (command, args) => {
            state.calls.push([command, args]);
            if (command === 'quick_chat_shortcut_platform') return state.platformGate ?? 'wayland';
            if (command === 'portal_shortcuts_bind') return state.bind?.(args) ?? {};
            if (command === 'quick_chat_show') state.actions.push('quick-chat');
            if (command === 'main_window_restore') state.actions.push('restore');
        };
        export const listen = async (name, callback) => {
            state.handlers.add(callback);
            await state.listenGate;
            return () => { state.handlers.delete(callback); state.removals++; };
        };
        export const register = async (key, callback) => {
            await state.registerGate;
            state.registered.set(key, callback);
        };
        export const unregister = async key => { state.removed.push(key); state.registered.delete(key); };
        export const unregisterAll = async () => { await state.unregisterGate; state.removed.push(...state.registered.keys()); state.registered.clear(); };
    `) + `#${crypto.randomUUID()}`;
    const { state, hot } = await import(dependencies);
    let instance = 0;
    const load = async () => {
        let source = await readFile(new URL("./useHotkeys.js", import.meta.url), "utf8");
        source = source.replace(/from "[^"]+"/g, `from ${JSON.stringify(dependencies)}`);
        source = `import { hot } from ${JSON.stringify(dependencies)};\n` + source.replaceAll("import.meta.hot", "hot");
        const module = await import(moduleUrl(source) + `#${instance++}`);
        return state.runtime ? module.useHotkeys : module.useHotkeys();
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

async function owner(platform = "native") {
    const subject = await setup(), runtime = hooks();
    subject.state.runtime = runtime;
    subject.state.platformGate = platform;
    const useHotkeys = await subject.load();
    let latest;
    const { GlobalHotKeyController } = await loadModule(new URL("../../../../views/app/_app_controllers/GlobalHotKeyController.jsx", import.meta.url), runtime, {
        "@logics_configs": { useHotkeys: () => { latest = useHotkeys(); return latest; } },
        "@logics_common": {
            useIsBackendReady: () => ({ currentIsBackendReady: { data: subject.state.ready } }),
            useIsSoftwareUpdating: () => ({ currentIsSoftwareUpdating: { data: subject.state.updating } }),
            useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: subject.state.settings } }),
        },
    });
    return { ...subject, runtime, render: async () => { runtime.render(GlobalHotKeyController); await flush(); },
        hook: () => latest };
}

for (const [action, oldKeys, newKeys] of [
    ["open_quick_chat", ["Ctrl", "Q"], ["Ctrl", "W"]],
    ["toggle_transcription_send", ["Ctrl", "M"], ["Ctrl", "N"]],
    ["toggle_transcription_send", ["Ctrl", "M"], null],
]) test(`close before ${action} ${newKeys ? "replacement" : "deletion"} acknowledgement reconciles native bindings`, async () => {
    const subject = await owner();
    subject.state.hotkeys = { [action]: oldKeys };
    await subject.render();
    const oldShortcut = `Control+${oldKeys[1]}`;
    assert.deepEqual([...subject.state.registered.keys()], [oldShortcut]);
    const oldCallback = subject.state.registered.get(oldShortcut);
    subject.state.settings = true;
    await subject.render();
    await subject.hook().setHotkeys({ [action]: newKeys });
    const acknowledged = subject.state.writes.at(-1)[1];
    subject.state.settings = false;
    await subject.render();
    assert.deepEqual([...subject.state.registered.keys()], [oldShortcut]);
    subject.hook().setSuccessHotkeys(acknowledged);
    await subject.render();
    assert.deepEqual([...subject.state.registered.keys()], newKeys ? [`Control+${newKeys[1]}`] : []);
    assert.ok(subject.state.removed.includes(oldShortcut));
    await oldCallback({ state: action === "open_quick_chat" ? "Released" : "Pressed" });
    assert.deepEqual(subject.state.actions, []);
    if (newKeys) {
        await subject.state.registered.get(`Control+${newKeys[1]}`)({ state: action === "open_quick_chat" ? "Released" : "Pressed" });
        assert.deepEqual(subject.state.actions, [action === "open_quick_chat" ? "quick-chat" : "send"]);
    }
    subject.runtime.unmount();
    await flush();
    assert.equal(subject.state.registered.size, 0);
});

test("a Space stored by older recordings as \" \" registers as Control+Space", async () => {
    const subject = await owner();
    subject.state.hotkeys = { open_quick_chat: ["Ctrl", " "] };
    await subject.render();
    assert.deepEqual([...subject.state.registered.keys()], ["Control+Space"]);
    subject.runtime.unmount();
    await flush();
});

test("an old native register completing after a new acknowledgement is released before the new binding", async () => {
    const subject = await owner(), gate = deferred();
    subject.state.registerGate = gate.promise;
    await subject.render();
    subject.hook().setSuccessHotkeys({ open_quick_chat: ["Ctrl", "W"] });
    await subject.render();
    gate.resolve();
    await flush();
    assert.deepEqual([...subject.state.registered.keys()], ["Control+W"]);
    assert.ok(subject.state.removed.includes("Control+Q"));
    subject.runtime.unmount();
    await flush();
});

test("portal reconciliation observes acknowledged content and does not rebind on identical data", async () => {
    const subject = await owner("wayland");
    await subject.render();
    subject.state.settings = true;
    await subject.render();
    subject.state.settings = false;
    await subject.render();
    subject.hook().setSuccessHotkeys({ open_quick_chat: ["Ctrl", "W"] });
    await subject.render();
    const binds = () => subject.state.calls.filter(([name]) => name === "portal_shortcuts_bind");
    assert.deepEqual(binds().at(-1)[1].shortcuts, { open_quick_chat: ["Ctrl", "W"] });
    const count = binds().length;
    subject.hook().setSuccessHotkeys({ open_quick_chat: ["Ctrl", "W"] });
    await subject.render();
    assert.equal(binds().length, count);
    subject.emit();
    assert.deepEqual(subject.state.actions, ["quick-chat"]);
    subject.state.settings = true;
    await subject.render();
    subject.emit();
    assert.deepEqual(subject.state.actions, ["quick-chat"]);
    subject.runtime.unmount();
});

test("Settings close controller leaves registration to its single owner", async () => {
    const source = await readFile(new URL("../../../../views/app/_app_controllers/ConfigPageCloseTriggerController.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(source, /useHotkeys|registerShortcuts|unregisterAll/);
});

for (const deletion of [false, true]) test(`overlapping hotkey ${deletion ? "deletion" : "assignment"} sends only the edited actions`, async () => {
    const subject = await setup(), gate = deferred();
    subject.state.platformGate = "native";
    subject.state.hotkeys = { toggle_translation: null, toggle_transcription_send: ["Ctrl", "M"] };
    subject.state.registerGate = gate.promise;
    const hook = await subject.load();
    const first = hook.setHotkeys({ toggle_translation: ["Ctrl", "T"] });
    await flush();
    const second = hook.setHotkeys({ toggle_transcription_send: deletion ? null : ["Ctrl", "N"] });
    gate.resolve();
    await Promise.all([first, second]);
    const final = Object.assign({}, ...subject.state.writes.map(([, value]) => value));
    assert.deepEqual(final, { toggle_translation: ["Ctrl", "T"], toggle_transcription_send: deletion ? null : ["Ctrl", "N"] });
    assert.ok(subject.state.writes.every(([, value]) => Object.keys(value).length === 1));
});

for (const boundary of ["preflight", "acknowledgement"]) test(`pending shortcut at ${boundary} cannot be assigned to a second action`, async () => {
    const subject = await setup(), gate = deferred();
    subject.state.platformGate = "native";
    subject.state.hotkeys = { toggle_translation: null, toggle_transcription_send: null };
    if (boundary === "preflight") subject.state.registerGate = gate.promise;
    else subject.state.writeGate = gate.promise;
    const hook = await subject.load();
    const first = hook.setHotkeys({ toggle_translation: ["Ctrl", "T"] });
    await flush();
    const second = hook.setHotkeys({ toggle_transcription_send: ["Ctrl", "T"] });
    await flush();
    gate.resolve(true);
    assert.equal(await second, false);
    await first;
    assert.equal(subject.state.writes.length, 1);
});

test("preflight rechecks the latest acknowledged content before saving", async () => {
    const subject = await setup(), gate = deferred();
    subject.state.platformGate = "native";
    subject.state.hotkeys = { toggle_translation: null, toggle_transcription_send: null };
    subject.state.registerGate = gate.promise;
    const hook = await subject.load();
    const edit = hook.setHotkeys({ toggle_translation: ["Ctrl", "T"] });
    await flush();
    hook.setSuccessHotkeys({ toggle_translation: null, toggle_transcription_send: ["Ctrl", "T"] });
    gate.resolve();
    assert.equal(await edit, false);
    assert.deepEqual(subject.state.writes, []);
});

test("a newer edit of the same action supersedes its pending preflight", async () => {
    const subject = await setup(), gate = deferred();
    subject.state.platformGate = "native";
    subject.state.hotkeys = { toggle_translation: null };
    subject.state.registerGate = gate.promise;
    const hook = await subject.load();
    const first = hook.setHotkeys({ toggle_translation: ["Ctrl", "T"] });
    await flush();
    const second = hook.setHotkeys({ toggle_translation: ["Ctrl", "N"] });
    gate.resolve();
    assert.equal(await first, false);
    assert.equal(await second, true);
    assert.deepEqual(subject.state.writes, [["/set/data/hotkeys", { toggle_translation: ["Ctrl", "N"] }]]);
});

test("a sent edit stays reserved until its acknowledgement even if the same action is edited again", async () => {
    const subject = await setup(), gate = deferred();
    subject.state.platformGate = "native";
    subject.state.hotkeys = { toggle_translation: null, toggle_transcription_send: null };
    subject.state.writeGate = gate.promise;
    const hook = await subject.load();
    const first = hook.setHotkeys({ toggle_translation: ["Ctrl", "T"] });
    await flush();
    assert.equal(await hook.setHotkeys({ toggle_translation: ["Ctrl", "N"] }), false);
    assert.equal(await hook.setHotkeys({ toggle_transcription_send: ["Ctrl", "T"] }), false);
    gate.resolve(true);
    await first;
    assert.equal(subject.state.writes.length, 1);
});

test("on Wayland the visibility hotkey restores the window it minimized", async () => {
    const subject = await setup();
    const { state } = subject;
    state.hotkeys = { toggle_vrct_visibility: ["Ctrl", "H"] };
    const hook = await subject.load();
    await hook.registerShortcuts();
    await flush();
    const press = async () => { for (const callback of state.handlers) callback({ payload: { id: "toggle_vrct_visibility" } }); await flush(); await flush(); };
    await press();
    assert.deepEqual(state.actions, ["minimize"]);
    // Wayland never reports a window as minimized; the second press must still bring it back.
    await press();
    assert.deepEqual(state.actions, ["minimize", "restore", "focus-input"]);
    await press();
    assert.deepEqual(state.actions, ["minimize", "restore", "focus-input", "minimize"]);
    // The user brought the window back by hand: the next press minimizes again.
    state.focusChanged({ payload: true });
    await press();
    assert.deepEqual(state.actions, ["minimize", "restore", "focus-input", "minimize", "minimize"]);
});

test("elsewhere the visibility hotkey asks the window whether it is minimized", async () => {
    const subject = await setup();
    const { state } = subject;
    state.platformGate = "native";
    state.hotkeys = { toggle_vrct_visibility: ["Ctrl", "H"] };
    const hook = await subject.load();
    await hook.registerShortcuts();
    await flush();
    const [[, press]] = [...state.registered];
    await press({ state: "Pressed" });
    await flush();
    state.minimized = true;
    await press({ state: "Pressed" });
    await flush();
    assert.deepEqual(state.actions, ["minimize", "unminimize", "set-focus", "focus-input"]);
    assert.ok(!state.calls.some(([command]) => command === "main_window_restore"));
});

test("the voice hotkeys press the controls the main window published", async () => {
    const subject = await setup();
    const { state } = subject;
    state.hotkeys = { stop_voice: ["Ctrl", "1"], toggle_voice_mute: ["Ctrl", "2"], toggle_tts: ["Ctrl", "3"], toggle_rvc: ["Ctrl", "4"] };
    const hook = await subject.load();
    await hook.registerShortcuts();
    await flush();
    assert.deepEqual(Object.keys(state.calls.find(([command]) => command === "portal_shortcuts_bind")[1].shortcuts),
        ["stop_voice", "toggle_voice_mute", "toggle_tts", "toggle_rvc"]);
    for (const id of ["stop_voice", "toggle_voice_mute", "toggle_tts", "toggle_rvc"]) {
        for (const callback of state.handlers) callback({ payload: { id } });
        await flush();
    }
    assert.deepEqual(state.actions, ["stop", "toggleMute", "toggleTts", "toggleRvc"]);
});
