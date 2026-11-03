import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import Babel from "@babel/standalone";
import React from "react";
import * as jsx from "react/jsx-runtime";
import clsx from "clsx";
import * as chatboxLength from "./chatboxLength.js";

// Exercise the production JSX handlers without a WebView or a new test runtime.
// Hooks retain state across explicit renders; IPC promises are controlled by tests.
function hooks() {
    const slots = [], effects = [];
    let index = 0;
    const memo = (factory, deps) => {
        const i = index++;
        if (!slots[i] || !deps || deps.some((v, n) => !Object.is(v, slots[i].deps[n]))) {
            slots[i] = { deps, value: factory() };
        }
        return slots[i].value;
    };
    const effect = (fn, deps) => memo(() => {
        effects.push(fn);
    }, deps);
    const cleanups = [];
    const api = { ...React,
        useState: initial => {
            const i = index++;
            if (!(i in slots)) slots[i] = typeof initial === "function" ? initial() : initial;
            return [slots[i], value => { slots[i] = typeof value === "function" ? value(slots[i]) : value; }];
        },
        useRef: initial => memo(() => ({ current: initial }), []),
        useMemo: memo, useCallback: (fn, deps) => memo(() => fn, deps),
        useEffect: effect, useLayoutEffect: effect,
    };
    return { api, render: (component, props) => {
        index = 0;
        const tree = component(props);
        effects.splice(0).forEach(fn => { const cleanup = fn(); if (cleanup) cleanups.push(cleanup); });
        return tree;
    }, unmount: () => cleanups.splice(0).forEach(fn => fn()) };
}

const icon = () => null;
async function load(path, runtime, imports = {}) {
    const source = await readFile(new URL(`../../views/${path}`, import.meta.url), "utf8");
    const { code } = Babel.transform(source, {
        presets: [["react", { runtime: "automatic" }]], plugins: ["transform-modules-commonjs"],
    });
    const dependencies = { react: runtime.api, "react/jsx-runtime": jsx, clsx,
        "@useI18n": { useI18n: () => ({ t: key => key }) }, ...imports };
    const require = name => {
        if (name.endsWith(".module.scss")) return new Proxy({}, { get: (_, key) => key === "__esModule" ? false : key });
        if (name.endsWith(".svg?react")) return icon;
        if (name in dependencies) return dependencies[name];
        throw new Error(`Unexpected component dependency: ${name}`);
    };
    const exports = {};
    new Function("require", "exports", code)(require, exports);
    return exports;
}

function find(tree, predicate) {
    if (!tree || typeof tree !== "object") return null;
    if (predicate(tree)) return tree;
    for (const child of React.Children.toArray(tree.props?.children)) {
        const found = find(child, predicate);
        if (found) return found;
    }
    return null;
}
const button = tree => find(tree, node => node.type === "button");
const switchNode = tree => find(tree, node => node.props?.role === "switch");
const actionPath = "app/config_page/setting_section/setting_box/_components/action_button/ActionButton.jsx";
const deferred = () => {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};

test("action feedback precedes a slow operation and repeated presses send only once", async context => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), work = deferred();
    const { ActionButton } = await load(actionPath, runtime);
    let calls = 0;
    const props = { IconComponent: icon, ClickedIconComponent: () => null, label: "Copy",
        onclickFunction: () => { calls++; return work.promise; } };
    const render = () => button(runtime.render(ActionButton, props));
    const initial = render();
    const pending = initial.props.onClick();
    await initial.props.onClick(); // Same handler, before React paints aria-disabled.
    const busy = render();
    assert.equal(calls, 1);
    assert.equal(busy.props["aria-busy"], true);
    assert.equal(busy.props["aria-disabled"], true);
    assert.equal(find(busy, node => node.type === props.ClickedIconComponent), null);
    work.resolve();
    await pending;
    const done = render();
    assert.equal(done.props["aria-busy"], false);
    assert.ok(find(done, node => node.type === props.ClickedIconComponent));
    await initial.props.onClick(); // Success-display cooldown also guards stale handlers.
    assert.equal(calls, 1);
    context.mock.timers.tick(1000);
    assert.equal(render().props["aria-disabled"], false);
    runtime.unmount();
});

test("a rejected action clears pending, reports the error and permits retry without success", async () => {
    const runtime = hooks(), work = deferred(), errors = [];
    const { ActionButton } = await load(actionPath, runtime);
    const props = { IconComponent: icon, ClickedIconComponent: () => null,
        onclickFunction: () => work.promise, onErrorFunction: error => errors.push(error) };
    const render = () => button(runtime.render(ActionButton, props));
    const pending = render().props.onClick();
    const error = new Error("clipboard unavailable");
    work.reject(error);
    await pending;
    const failed = render();
    assert.equal(failed.props["aria-disabled"], false);
    assert.equal(failed.props["aria-busy"], false);
    assert.equal(find(failed, node => node.type === props.ClickedIconComponent), null);
    assert.deepEqual(errors, [error]);
    let retried = false;
    props.onclickFunction = () => { retried = true; };
    props.ClickedIconComponent = undefined;
    await render().props.onClick();
    assert.equal(retried, true);
    assert.equal(render().props["aria-disabled"], false);
    runtime.unmount();
});

test("an action settling after its settings page closes does not schedule success feedback", async context => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), work = deferred();
    const { ActionButton } = await load(actionPath, runtime);
    const props = { IconComponent: icon, ClickedIconComponent: () => null, onclickFunction: () => work.promise };
    const pending = button(runtime.render(ActionButton, props)).props.onClick();
    runtime.unmount();
    work.resolve();
    await pending;
    context.mock.timers.tick(1000);
    assert.equal(find(runtime.render(ActionButton, props), node => node.type === props.ClickedIconComponent), null);
});

test("settings switches reject pointer and keyboard repeats while retaining the confirmed value", async () => {
    const runtime = hooks();
    const { _SwitchBox } = await load("app/config_page/setting_section/setting_box/_components/_atoms/_switch_box/_SwitchBox.jsx", runtime);
    let calls = 0;
    const props = { variable: { state: "pending", data: false }, toggleFunction: () => calls++ };
    for (const confirmed of [false, true]) {
        props.variable.data = confirmed;
        const control = switchNode(runtime.render(_SwitchBox, props));
        control.props.onClick();
        for (const key of [" ", "Enter"]) control.props.onKeyDown({ key, preventDefault() {} });
        assert.equal(control.props["aria-checked"], confirmed);
        assert.equal(control.props["aria-disabled"], true);
    }
    assert.equal(calls, 0);
    props.variable.state = "ok";
    switchNode(runtime.render(_SwitchBox, props)).props.onClick();
    assert.equal(calls, 1);
});

test("main switches block pending repeats but TTS/RVC cancellation remains available", async () => {
    const runtime = hooks();
    const { SwitchContainer } = await load("app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch.jsx", runtime, {
        "@store": { store: {} },
        "../../../../../logics/common/useNotificationStatus": {},
        "../../../../../logics/voice/useVoice": {},
        "@logics_main": { useIsMainPageCompactMode: () => ({ currentIsMainPageCompactMode: { data: false } }) },
        "../../../../common_components/toggle_switch/ToggleSwitch": { ToggleSwitch: icon },
    });
    let calls = 0;
    const props = { currentState: { data: false, state: "pending" }, SvgComponent: icon, toggleFunction: () => calls++ };
    const press = () => {
        const control = switchNode(runtime.render(SwitchContainer, props));
        control.props.onClick();
        control.props.onKeyDown({ key: "Enter", preventDefault() {} });
        assert.equal(control.props["aria-checked"], false);
        return control;
    };
    assert.equal(press().props["aria-disabled"], true);
    assert.equal(calls, 0);
    props.cancellable = true;
    assert.equal(press().props["aria-disabled"], false);
    assert.equal(calls, 2);
    props.disabled = true;
    assert.equal(press().props["aria-disabled"], true);
    assert.equal(calls, 2);
});

test("message actions keep the same context value and delegate to the latest existing send hook", async () => {
    const runtime = hooks(), sent = [], edited = [], typing = [];
    let version = 0;
    const { MessageActionsProvider } = await load("../logics/common/MessageActions.jsx", runtime, {
        "./useMessage": { useMessage: () => {
            const currentVersion = version;
            return {
                sendMessage: text => sent.push([currentVersion, text]),
                updateMessageInputValue: text => edited.push([currentVersion, text]),
                startTyping: () => typing.push([currentVersion, "start"]),
                stopTyping: () => typing.push([currentVersion, "stop"]) };
        } },
    });
    const children = React.createElement("div");
    const initial = runtime.render(MessageActionsProvider, { children });
    version++;
    const next = runtime.render(MessageActionsProvider, { children });
    assert.equal(next.props.value, initial.props.value);
    assert.equal(next.props.children, initial.props.children);
    assert.deepEqual(sent, []);
    assert.deepEqual(edited, []);
    initial.props.value.sendMessage("resend");
    initial.props.value.updateMessageInputValue("edit");
    initial.props.value.startTyping();
    initial.props.value.stopTyping();
    assert.deepEqual(sent, [[1, "resend"]]);
    assert.deepEqual(edited, [[1, "edit"]]);
    assert.deepEqual(typing, [[1, "start"], [1, "stop"]]);
});

test("LogBox subscribes only to its log and resend setting; unchanged row props stay stable", async () => {
    const runtime = hooks(), subscriptions = [];
    const message = { id: "first", messages: { original: { message: "hello" }, translations: [] } };
    let logs = [message];
    const actions = { sendMessage() {}, updateMessageInputValue() {} };
    const { LogBox } = await load("app/main_page/main_section/message_container/log_box/LogBox.jsx", runtime, {
        "./message_container/MessageContainer": { MessageContainer: React.memo(icon) },
        "jotai": { useAtomValue: atom => { assert.equal(atom, "logs"); subscriptions.push(atom); return { data: logs }; } },
        "@store": { store: {}, Atom_MessageLogs: "logs" },
        "@logics_common": { useMessageActions: () => actions },
        "@logics_main": { useMessageLogScroll: () => ({ scrollToBottom() {}, isScrolling: false }) },
        "@logics_configs": { useSettingValue: name => { subscriptions.push(name); return { data: true }; } },
    });
    assert.equal(LogBox.$$typeof, Symbol.for("react.memo"));
    const rows = () => find(runtime.render(LogBox.type), node => node.props?.messages);
    const initial = rows();
    const typed = rows();
    // Every prop is Object.is-equal: React.memo skips the entire list traversal.
    for (const key of Object.keys(initial.props)) assert.equal(typed.props[key], initial.props[key]);
    assert.deepEqual(subscriptions, ["logs", "ShowResendButton", "logs", "ShowResendButton"]);
    const before = initial.type.type(initial.props);
    logs = [...logs, { ...message, id: "second" }];
    const appended = rows();
    const after = appended.type.type(appended.props);
    assert.equal(after.length, 2);
    for (const key of Object.keys(before[0].props)) assert.equal(after[0].props[key], before[0].props[key]);
    logs = [{ ...message, status: "ok", messages: { ...message.messages, translations: [{ message: "translated" }] } }, logs[1]];
    const confirmed = rows();
    const confirmedRows = confirmed.type.type(confirmed.props);
    assert.equal(confirmedRows[0].props.status, "ok");
    assert.equal(confirmedRows[0].props.messages, logs[0].messages);
    for (const key of Object.keys(after[1].props)) assert.equal(confirmedRows[1].props[key], after[1].props[key]);
});

test("composer reads history only on explicit recall and sees the latest retained rows", async () => {
    const runtime = hooks(), edited = [], sent = [], typing = [], settingReads = [];
    let reads = 0, input = "", composing = false;
    let logs = [{ category: "sent", messages: { original: { message: "older" } } },
        { category: "received", messages: { original: { message: "incoming" } } },
        { category: "sent", messages: { original: { message: "newest" } } }];
    const { MessageInputBox } = await load("app/main_page/main_section/message_container/message_input_box/MessageInputBox.jsx", runtime, {
        "@store": { store: {}, Atom_MessageLogs: "logs", useStore_MessageInputValue: () => ({
            currentMessageInputValue: { data: input }, updateMessageInputValue: text => { input = text; edited.push(text); },
        }) },
        "jotai": { useStore: () => ({ get: atom => { assert.equal(atom, "logs"); reads++; return { data: logs }; } }) },
        "@logics_common": { useMessageActions: () => ({ sendMessage: text => sent.push(text),
            startTyping: () => typing.push("start"), stopTyping: () => typing.push("stop") }) },
        "@logics_configs": { useSettingValue: name => {
            settingReads.push(name);
            return { data: name === "SendMessageButtonType" ? "show" : true };
        } },
        "@logics_main": { useMessageLogScroll: () => ({ scrollToBottom() {} }) },
        "../../../../../../logics/common/chatboxLength": chatboxLength,
        "./ChatboxLengthWarning": { CHATBOX_LENGTH_WARNING_ID: "chatbox_length_warning" },
    });
    assert.equal(MessageInputBox.$$typeof, Symbol.for("react.memo"));
    const render = () => find(runtime.render(MessageInputBox.type), node => node.type === "textarea");
    const key = (name, shiftKey = false) => render().props.onKeyDown({ key: name, keyCode: name === "Enter" ? 13 : 0,
        shiftKey, nativeEvent: { isComposing: composing }, preventDefault() {} });
    render();
    key("a");
    render().props.onChange({ currentTarget: { value: "a" } });
    assert.equal(reads, 0);
    assert.deepEqual(typing, ["start"]);
    assert.deepEqual([...new Set(settingReads)], ["EnableAutoClearMessageInputBox", "SendMessageButtonType"]);
    key("ArrowUp", true);
    assert.equal(input, "newest");
    key("ArrowUp", true);
    assert.equal(input, "older");
    key("ArrowDown", true);
    assert.equal(input, "newest");
    key("ArrowDown", true);
    assert.equal(input, "");
    // Retention/clear and incoming captions need no composer subscription.
    logs = [{ category: "sent", messages: { original: { message: "after cap/clear" } } }];
    key("ArrowUp", true);
    assert.equal(input, "after cap/clear");
    const readsBeforeIme = reads;
    composing = true;
    key("ArrowUp", true);
    key("Enter");
    assert.equal(reads, readsBeforeIme);
    assert.deepEqual(sent, []);
    composing = false;
    key("Enter");
    assert.deepEqual(sent, ["after cap/clear"]);
    assert.equal(input, "");
    assert.equal(reads, readsBeforeIme);
});

test("the window geometry controller keeps its listeners and only sends layout changes", async t => {
    const runtime = hooks(), listened = [], disposed = [], updates = [];
    let width = 870, scaling = 100;
    const listen = name => () => { listened.push(name); return Promise.resolve(() => disposed.push(name)); };
    const appWindow = { innerSize: async () => ({ width }), onResized: listen("resized"), onMoved: listen("moved") };
    const attributes = new Set();
    globalThis.document = { documentElement: {
        hasAttribute: name => attributes.has(name),
        toggleAttribute: (name, on) => { if (on) attributes.add(name); else attributes.delete(name); },
    } };
    t.after(() => { delete globalThis.document; });
    const { WindowGeometryController } = await load("../logics/common/useWindow.js", runtime, {
        "@tauri-apps/api/window": {},
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython() {} }) },
        "@store": { store: { appWindow }, useStore_IsBreakPoint: () => ({ updateIsBreakPoint: value => updates.push(value) }) },
        "@logics_configs": { useAppearance: () => ({ currentUiScaling: { data: scaling } }) },
    });
    const settle = () => new Promise(resolve => setTimeout(resolve));
    // A module-level component: re-rendering its parent must not remount it.
    for (let i = 0; i < 3; i++) runtime.render(WindowGeometryController);
    await settle();
    assert.deepEqual(listened, ["resized", "moved"]);
    assert.deepEqual(updates, []); // 870 px at 100 % is wide, as the layout already is
    width = 700; scaling = 120;
    runtime.render(WindowGeometryController);
    await settle();
    runtime.render(WindowGeometryController);
    await settle();
    assert.deepEqual(updates, [true]);
    assert.deepEqual(listened, ["resized", "moved"]);
    runtime.unmount();
    await settle();
    assert.deepEqual(disposed, ["resized", "moved"]);
});

test("opening and closing settings keeps the same MainSection type and key mounted", async () => {
    const runtime = hooks();
    let open = false;
    const MainSection = () => null;
    const { MainPage } = await load("app/main_page/MainPage.jsx", runtime, {
        "@logics_common": { useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: open } }) },
        "./sidebar_section/SidebarSection": { SidebarSection: icon },
        "./main_section/MainSection": { MainSection },
    });
    const initial = find(runtime.render(MainPage), node => node.type === MainSection);
    for (const state of [true, false]) {
        open = state;
        const page = runtime.render(MainPage);
        const section = find(page, node => node.type === MainSection);
        assert.equal(page.props["aria-hidden"], state);
        assert.equal(section.type, initial.type);
        assert.equal(section.key, initial.key);
    }
});

test("memoized log rows expose pending status and keep edit/resend explicit", async () => {
    const runtime = hooks(), sent = [], edited = [];
    const menu = () => null;
    const { MessageContainer } = await load("app/main_page/main_section/message_container/log_box/message_container/MessageContainer.jsx", runtime, {
        "@store": { store: {} },
        "./message_sub_menu_container/MessageSubMenuContainer": { MessageSubMenuContainer: menu },
        // A row must not subscribe to the global log/input or settings hooks.
    });
    assert.equal(MessageContainer.$$typeof, Symbol.for("react.memo"));
    const props = { messages: { original: { message: "hello", transliteration: [] }, translations: [] },
        status: "pending", category: "sent", created_at: "12:00", showResendButton: true,
        sendMessage: text => sent.push(text), updateMessageInputValue: text => edited.push(text) };
    const render = () => runtime.render(MessageContainer.type, props);
    assert.ok(find(render(), node => node.props?.className === "loader"));
    assert.deepEqual(sent, []);
    const controls = find(render(), node => node.type === menu);
    controls.props.editFunction();
    controls.props.resendFunction();
    assert.deepEqual(edited, ["hello"]);
    assert.deepEqual(sent, ["hello"]);
    props.status = "ok";
    assert.equal(find(render(), node => node.props?.className === "loader"), null);
    props.showResendButton = false;
    assert.equal(find(render(), node => node.type === menu), null);
});
