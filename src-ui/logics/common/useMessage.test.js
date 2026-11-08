import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import i18next from "i18next";
import yaml from "js-yaml";
import { find, hooks, loadModule } from "../test/hookHarness.js";
import { loadBridgeRoutes, deferred, flush } from "../test/bridgeHarness.js";
import { keepRecentLogs } from "./messageLogLimit.js";
import * as chatboxLength from "./chatboxLength.js";
import { decodeLogUpdate, encodeLogUpdate } from "./vrPanelWire.js";

async function setup(send = async () => true, reset = async () => true, i18n = null) {
    let useMessage;
    const writes = [], typingWrites = [], endpoints = [];
    const subject = await loadBridgeRoutes(async ({ runtime, stores }) => {
        ({ useMessage } = await loadModule(new URL("./useMessage.js", import.meta.url), runtime, {
            "@store": stores,
            ...i18n && { "@useI18n": { useI18n: () => ({ t: i18n.t.bind(i18n), i18n }) } },
            "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: (...args) => {
                endpoints.push(args[0]);
                if (args[0] !== "/run/send_message_box") {
                    typingWrites.push(args[0]);
                    return reset(...args);
                }
                writes.push(args);
                return send(...args);
            } }) },
            "../transcription/useRealtimeASR": {}, "../transcription/realtimeCaptionState": {},
            "./messageLogLimit": { keepRecentLogs },
        }));
        return { useMessage };
    }, i18n);
    return { ...subject, writes, typingWrites, endpoints, message: subject.runtime.render(useMessage),
        rows: () => subject.runtime.store.get(subject.stores.Atom_MessageLogs).data,
        receive: (status, result) => subject.receiveRoutes({ endpoint: "/run/send_message_box", status, result }),
    };
}

for (const mode of ["false", "throw", "reject"]) test(`send ${mode} resolves only its row as failed without retry`, async () => {
    const subject = await setup((_, data) => {
        if (data.id === "other") return true;
        if (mode === "throw") throw Error("transport failed");
        return mode === "reject" ? Promise.reject(Error("transport failed")) : false;
    });
    await subject.message.sendMessage("Still waiting", "other");
    assert.equal(await subject.message.sendMessage("Keep this text", "failed"), false);
    assert.deepEqual(subject.rows().map(row => [row.id, row.status]), [["other", "pending"], ["failed", "failed"]]);
    assert.equal(subject.rows()[1].messages.original.message, "Keep this text");
    assert.equal(subject.writes.length, 2);
    assert.deepEqual(subject.typingWrites, ["/run/stop_typing_message_box", "/run/stop_typing_message_box"]);
});

for (const status of [400, 404, 423, 500]) test(`terminal ${status} response clears pending and a late success can settle an uncertain row`, async context => {
    context.mock.method(console, "error", () => {});
    const subject = await setup();
    await subject.message.sendMessage("First", "first");
    await subject.message.sendMessage("Second", "second");
    subject.receive(status, { message: "failure", error_code: "unknown" });
    assert.deepEqual(subject.rows().map(row => row.status), ["failed", "failed"]);
    subject.receive(200, { id: "first", translations: [{ message: "translated", transliteration: [] }] });
    assert.deepEqual(subject.rows().map(row => row.status), ["ok", "failed"]);
    assert.equal(subject.rows()[0].messages.translations[0].message, "translated");
    assert.equal(subject.writes.length, 2);
    assert.deepEqual(subject.reads, []);
});

test("a correlated error only settles that pending row", async context => {
    context.mock.method(console, "error", () => {});
    const subject = await setup();
    await subject.message.sendMessage("First", "first");
    await subject.message.sendMessage("Second", "second");
    subject.receive(423, { data: { id: "second" } });
    assert.deepEqual(subject.rows().map(row => row.status), ["pending", "failed"]);
});

test("successful transport stays pending until a success response, including an immediate response", async () => {
    const subject = await setup();
    await subject.message.sendMessage("Hello", "ok");
    subject.receive(348, {});
    assert.equal(subject.rows()[0].status, "pending");
    subject.receive(200, { id: "ok", translations: [] });
    assert.equal(subject.rows()[0].status, "ok");
    const immediate = await setup((_, data) => {
        immediate.receive(200, { id: data.id, translations: [] });
        return true;
    });
    await immediate.message.sendMessage("Hello", "immediate");
    assert.equal(immediate.rows()[0].status, "ok");
});

test("late transport failure cannot downgrade success; backend stop settles remaining pending sends", async () => {
    const write = deferred();
    const subject = await setup(() => write.promise);
    const sent = subject.message.sendMessage("Hello", "ok");
    subject.receive(200, { id: "ok", translations: [] });
    write.resolve(false);
    await sent;
    assert.equal(subject.rows()[0].status, "ok");
    const waiting = await setup();
    await waiting.message.sendMessage("Hello", "waiting");
    waiting.backendStopped();
    assert.equal(waiting.rows()[0].status, "failed");
    assert.equal(waiting.writes.length, 1);
});

test("submit resets typing before an outstanding send and keeps the two-second start cooldown", async context => {
    let now = 2000;
    context.mock.method(Date, "now", () => now);
    const write = deferred(), subject = await setup(() => write.promise);
    subject.message.startTyping();
    const sent = subject.message.sendMessage("Hello", "pending");
    assert.deepEqual(subject.endpoints, ["/run/typing_message_box", "/run/stop_typing_message_box", "/run/send_message_box"]);
    assert.equal(subject.rows()[0].status, "pending");
    now = 3999;
    subject.message.startTyping();
    assert.equal(subject.typingWrites.length, 2);
    now = 4000;
    subject.message.startTyping();
    assert.equal(subject.typingWrites.at(-1), "/run/typing_message_box");
    assert.equal(subject.typingWrites.length, 3);
    write.resolve(true);
    await sent;
});

test("empty submissions reset typing without creating or sending a row", async () => {
    const subject = await setup();
    for (const value of ["", " \n\t", null]) assert.equal(await subject.message.sendMessage(value), false);
    assert.deepEqual(subject.rows(), []);
    assert.deepEqual(subject.writes, []);
    assert.deepEqual(subject.typingWrites, Array(3).fill("/run/stop_typing_message_box"));
});

for (const mode of ["throw", "reject"]) test(`a reset ${mode} does not block message settlement`, async () => {
    const subject = await setup(async () => true, () => {
        if (mode === "throw") throw Error("reset failed");
        return Promise.reject(Error("reset failed"));
    });
    assert.equal(await subject.message.sendMessage("Hello", "ok"), true);
    subject.receive(200, { id: "ok", translations: [] });
    assert.equal(subject.rows()[0].status, "ok");
});

for (const failed of [false, true]) test(`acknowledgement preserves original readings and translations after ${failed ? "unconfirmed" : "pending"} state, including VR mirroring`, async () => {
    const subject = await setup();
    await subject.message.sendMessage("日本語", "readings");
    const before = subject.rows(), pending = before[0];
    if (failed) subject.message.failSentMessageLog({ id: "readings" });
    const original = { message: "日本語", transliteration: [{ orig: "日本語", hira: "にほんご", hepburn: "nihongo" }] };
    const translations = [{ message: "Japanese", transliteration: [] }];
    subject.receive(200, { id: "readings", original, translations });
    assert.deepEqual(subject.rows()[0], { ...pending, status: "ok", messages: { original, translations } });
    const first = encodeLogUpdate(null, { state: "ok", data: before });
    const mirror = decodeLogUpdate(null, first.message);
    const update = encodeLogUpdate(first.sent, { state: "ok", data: subject.rows() });
    assert.deepEqual(decodeLogUpdate(mirror, update.message).rows, subject.rows());
    subject.message.failSentMessageLog({ id: "readings" });
    assert.equal(subject.rows()[0].status, "ok");
});

test("translation-off acknowledgements retain original readings and partial replies retain existing content", async () => {
    const subject = await setup();
    await subject.message.sendMessage("日本語", "original");
    const original = { message: "日本語", transliteration: [{ orig: "日本語", hira: "にほんご", hepburn: "nihongo" }] };
    subject.receive(200, { id: "original", original, translations: [] });
    subject.receive(200, { id: "original" });
    assert.deepEqual(subject.rows()[0].messages, { original, translations: [] });
});

async function composer(subject, autoClear = false) {
    const runtime = hooks();
    runtime.store = subject.runtime.store;
    const { MessageInputBox } = await loadModule(new URL("../../views/app/main_page/main_section/message_container/message_input_box/MessageInputBox.jsx", import.meta.url), runtime, {
        "@store": subject.stores,
        "@logics_common": { useMessageActions: () => subject.message },
        "@logics_configs": { useSettingValue: name => ({ data: name === "SendMessageButtonType" ? "show" : autoClear }) },
        "@logics_main": { useMessageLogScroll: () => ({ scrollToBottom() {} }) },
        "../../../../../../logics/common/chatboxLength": chatboxLength,
        "./ChatboxLengthWarning": { CHATBOX_LENGTH_WARNING_ID: "length-warning" },
    });
    const render = () => runtime.render(MessageInputBox.type);
    const field = () => find(render(), node => node.type === "textarea");
    return { render, field, input: () => runtime.store.get(subject.stores.Atom_MessageInputValue).data,
        change: value => { field().props.onChange({ currentTarget: { value } }); render(); },
        enter: (extra = {}) => field().props.onKeyDown({ key: "Enter", keyCode: 13, nativeEvent: {}, preventDefault() {}, ...extra }),
        key: key => field().props.onKeyDown({ key, shiftKey: true, nativeEvent: {}, preventDefault() {} }),
    };
}

for (const success of [true, false]) for (const autoClear of [true, false]) {
    test(`desktop Enter resets typing with success=${success}, auto-clear=${autoClear}`, async context => {
        context.mock.method(globalThis, "setTimeout", () => 0);
        const subject = await setup(async () => success), input = await composer(subject, autoClear);
        input.change("Hello");
        input.enter();
        input.render();
        await flush();
        assert.equal(subject.typingWrites.at(-1), "/run/stop_typing_message_box");
        assert.equal(subject.rows()[0].status, success ? "pending" : "failed");
        assert.equal(input.input(), autoClear ? "" : "Hello");
        const sendIndex = subject.endpoints.indexOf("/run/send_message_box");
        assert.equal(subject.endpoints[sendIndex - 1], "/run/stop_typing_message_box");
    });
}

test("desktop empty submit, user clear, programmatic clear and blur reset typing", async () => {
    const subject = await setup(), input = await composer(subject);
    input.change("Hello");
    input.change(" ");
    assert.equal(subject.typingWrites.at(-1), "/run/stop_typing_message_box");
    const beforeEmptySubmit = subject.typingWrites.length;
    input.enter();
    assert.equal(subject.typingWrites.length, beforeEmptySubmit + 1);
    assert.equal(subject.rows().length, 0);
    assert.equal(subject.writes.length, 0);
    input.change("Hello again");
    const beforeClear = subject.typingWrites.length;
    subject.message.updateMessageInputValue("");
    input.render();
    assert.equal(subject.typingWrites.length, beforeClear + 1);
    input.change("Retained draft");
    input.field().props.onBlur();
    assert.equal(subject.typingWrites.at(-1), "/run/stop_typing_message_box");
});

for (const success of [true, false]) test(`Quick Chat handoff resets typing and preserves acceptance=${success}`, async () => {
    const subject = await setup(async () => success), runtime = hooks(), finished = [];
    let receive, request = null;
    const { QuickChatController } = await loadModule(new URL("../../views/app/_app_controllers/QuickChatController.jsx", import.meta.url), runtime, {
        "@tauri-apps/api/core": { invoke: async (name, args) => {
            if (name === "quick_chat_take") { const next = request; request = null; return next; }
            if (name === "quick_chat_finish") finished.push(args);
        } },
        "@tauri-apps/api/event": { listen: async (_, callback) => { receive = callback; return () => {}; } },
        "@useI18n": { useI18n: () => ({ i18n: { language: "en" } }) },
        "../../../logics/common/useMessage": { useMessage: () => subject.message },
        "@logics_common": {
            useIsBackendReady: () => ({ currentIsBackendReady: { data: true } }),
            useIsSoftwareUpdating: () => ({ currentIsSoftwareUpdating: { data: false } }),
            useIsOpenedConfigPage: () => ({ currentIsOpenedConfigPage: { data: false } }),
        },
        "@logics_configs": {
            useAppearance: () => ({ currentSendMessageButtonType: { data: "show" },
                currentUiScaling: { data: 100 }, currentSelectedFontFamily: { data: "Yu Gothic UI" } }),
            useOthers: () => ({ currentEnableAutoClearMessageInputBox: { data: true } }),
        },
    });
    runtime.render(QuickChatController);
    await flush();
    request = { id: "quick", message: "日本語" };
    await receive();
    assert.deepEqual(subject.endpoints, ["/run/stop_typing_message_box", "/run/send_message_box"]);
    assert.deepEqual(finished, [{ id: "quick", accepted: success }]);
    assert.equal(subject.rows()[0].status, success ? "pending" : "failed");
    if (success) {
        const original = { message: "日本語", transliteration: [{ orig: "日本語", hira: "にほんご", hepburn: "nihongo" }] };
        subject.receive(200, { id: "quick", original, translations: [] });
        assert.deepEqual(subject.rows()[0].messages.original, original);
    }
    runtime.unmount();
});

test("output failure warns without failing or resending a successful message row", async () => {
    const subject = await setup();
    await subject.message.sendMessage("Original", "partial");
    subject.receiveRoutes({ status: 400, endpoint: "/run/message_output_error", result: {
        error_code: "MESSAGE_OUTPUT_FAILED", data: { id: "partial", source: "chat", output: "overlay_large" },
    } });
    assert.equal(subject.rows()[0].status, "pending");
    const original = { message: "Original", transliteration: [{ orig: "Original", hira: "reading" }] };
    subject.receive(200, { id: "partial", original, translations: [], output_failures: [{ output: "overlay_large" }] });
    assert.equal(subject.rows()[0].status, "ok");
    assert.deepEqual(subject.rows()[0].messages.original, original);
    assert.equal(subject.notices[0].type, "warning");
    assert.equal(subject.notices[0].options.category_id, "MESSAGE_OUTPUT_FAILED.overlay_large");
    assert.equal(subject.writes.length, 1);
    assert.deepEqual(subject.reads, []);
});

const locale = language => yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
// Every code the sidecar puts on /run/transcription_recognition_error.
const RECOGNITION_FAILURES = ["AUDIO_OPEN_ERROR", "AUDIO_READ_ERROR", "VAD_INFERENCE_ERROR",
    "TRANSCRIBER_INIT_ERROR", "ASR_ERROR", "CLEANUP_TIMEOUT"];

for (const language of ["en", "ja"]) test(`${language}: recognition failures are logged in the UI language, naming the Windows question for the microphone`, async () => {
    const translation = locale(language);
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, resources: { [language]: { translation } }, interpolation: { escapeValue: false } });
    const subject = await setup(undefined, undefined, i18n);
    const log = result => subject.receiveRoutes({ status: 200, endpoint: "/run/transcription_recognition_error", result });
    const failure = (error_code, source) => ({ error_code, stage: "recording", source, message: "English default", recoverable: false });
    log(failure("AUDIO_OPEN_ERROR", "mic"));
    log(failure("AUDIO_OPEN_ERROR", "speaker"));
    log(failure("ASR_ERROR", "mic"));
    log({ message: "Mic speech recognition request failed. Check your network connection.", data: null });
    log(failure("NOT_A_CODE", "mic"));
    const errors = translation.backend_errors;
    assert.deepEqual(subject.rows().map(row => [row.category, row.messages.original.message]), [
        ["system", errors.AUDIO_OPEN_ERROR_mic], ["system", errors.AUDIO_OPEN_ERROR_speaker], ["system", errors.ASR_ERROR],
        ["system", "Mic speech recognition request failed. Check your network connection."], ["system", "English default"],
    ]);
    assert.match(errors.AUDIO_OPEN_ERROR_mic, /Windows/);
    assert.doesNotMatch(errors.AUDIO_OPEN_ERROR_speaker, /Windows/);
    for (const code of RECOGNITION_FAILURES) assert.ok(errors[code], code);
    assert.deepEqual(subject.reads, []);
});

for (const accepted of [true, false]) test(`holding Enter and duplicate clicks send once until handoff settles (${accepted})`, async context => {
    context.mock.method(globalThis, "setTimeout", () => 0);
    const handoff = deferred(), subject = await setup(() => handoff.promise), input = await composer(subject);
    input.change("同じ下書き");
    input.enter();
    input.enter({ repeat: true });
    input.enter({ repeat: true });
    input.enter(); // Another non-repeat keydown before the handoff settles.
    const button = find(input.render(), node => typeof node.props.onSubmitFunction === "function");
    assert.equal(button.props.pending, true);
    button.props.onSubmitFunction({ preventDefault() {} });
    assert.equal(subject.writes.length, 1);
    handoff.resolve(accepted);
    await flush();
    input.enter({ repeat: true }); // Still held after settlement: never resend.
    assert.equal(subject.writes.length, 1);
    assert.equal(input.input(), "同じ下書き");
    assert.equal(find(input.render(), node => typeof node.props.onSubmitFunction === "function").props.pending, false);
    input.enter(); // A deliberate later message, including identical text, is allowed.
    await flush();
    assert.equal(subject.writes.length, 2);
    assert.notEqual(subject.writes[0][1].id, subject.writes[1][1].id);
});

test("main input keeps IME and Shift+Enter guards", async () => {
    const subject = await setup(), input = await composer(subject);
    input.change("変換中");
    input.enter({ nativeEvent: { isComposing: true } });
    input.enter({ keyCode: 229 });
    input.enter({ shiftKey: true });
    assert.equal(subject.writes.length, 0);
});

const sentRow = (id, message) => ({ id, category: "sent", messages: { original: { message } } });
test("history eviction resets to the saved draft and never puts a non-string in the composer", async () => {
    const subject = await setup(), input = await composer(subject);
    const setRows = rows => subject.runtime.store.set(subject.stores.Atom_MessageLogs, { state: "ok", data: rows });
    let rows = [sentRow("oldest", "古い文"), sentRow("newer", "新しい文"),
        ...Array.from({ length: 998 }, (_, id) => ({ id: `received-${id}`, category: "received" }))];
    setRows(rows);
    input.change("書きかけの文章");
    input.key("ArrowUp");
    input.key("ArrowUp");
    assert.equal(input.input(), "古い文");
    rows = keepRecentLogs([...rows, { category: "received" }, { category: "received" }]);
    setRows(rows);
    input.key("ArrowDown");
    assert.equal(input.input(), "書きかけの文章");
    input.key("ArrowDown");
    input.key("ArrowUp");
    assert.equal(input.input(), "書きかけの文章");
    input.render(); // Includes the trim/typing effect that used to throw.
    assert.equal(subject.writes.length, 0);
});

test("history follows row identity through appended rows and partial eviction, then restores the draft", async () => {
    const subject = await setup(), input = await composer(subject);
    const setRows = rows => subject.runtime.store.set(subject.stores.Atom_MessageLogs, { state: "ok", data: rows });
    setRows([sentRow("a", "same"), sentRow("b", "same")]);
    input.change("draft");
    input.key("ArrowUp");
    setRows([sentRow("b", "same"), sentRow("c", "new"), sentRow("bad", undefined)]);
    input.key("ArrowDown");
    assert.equal(input.input(), "new");
    input.key("ArrowDown");
    assert.equal(input.input(), "draft");
    input.key("ArrowUp");
    input.change("edited history becomes a draft");
    input.key("ArrowUp");
    input.key("ArrowDown");
    assert.equal(input.input(), "edited history becomes a draft");
});
