import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { pendingRequestRecovery } from "./pendingRequestRecovery.js";
import { rejectExpectedExit } from "./sidecarExitExpectation.js";

const moduleUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
async function setup() {
    // Exercise the actual transport adapter; only Tauri, hooks and the language
    // owner are stubs. The recovery module is the real relative .js module.
    const dependencies = moduleUrl(`
        export const store = {backend_subprocess: null, backend_session: {expectedExits: new Map()}};
        export const events = [], notices = [];
        export const encode = value => Buffer.from(value).toString('base64');
        export const emit = async (...args) => events.push(['relay', ...args]);
        export const useI18n = () => ({t: key => key});
        export const useNotificationStatus = () => ({showNotification_Error: (...args) => notices.push(args)});
        export const isLanguageMutation = path => path === '/set/data/selected_target_languages';
        export const beginLanguageMutation = request => { events.push(['begin', request.requestId]); return !store.rejectLanguage; };
        export const createLanguageRequestId = () => 'language-request';
        export const getLanguageSnapshot = () => ({});
        export const failLanguageMutationBeforeSend = id => events.push(['before-send', id]);
        export const languageMutationWriteUnconfirmed = id => events.push(['unconfirmed', id]);
        export const failLanguageRead = endpoint => events.push(['read-failed', endpoint]);
    `) + `#${crypto.randomUUID()}`;
    const deps = await import(dependencies);
    let source = await readFile(new URL("./useStdoutToPython.js", import.meta.url), "utf8");
    for (const name of ["@store", "js-base64", "./useNotificationStatus", "@useI18n", "@tauri-apps/api/event", "../main/languageMutations"])
        source = source.replace(JSON.stringify(name), JSON.stringify(dependencies));
    source = source.replace('"./pendingRequestRecovery.js"', JSON.stringify(new URL("./pendingRequestRecovery.js", import.meta.url).href));
    source = source.replace('"./sidecarExitExpectation.js"', JSON.stringify(new URL("./sidecarExitExpectation.js", import.meta.url).href));
    const { useStdoutToPython } = await import(moduleUrl(source));
    let value = { state: "pending", data: 9000 };
    pendingRequestRecovery.register({ endpoints: ["/set/data/osc_port", "/get/data/osc_port"], read: "/get/data/osc_port",
        restore: () => { const changed = value.state === "pending"; value = { ...value, state: "ok" }; return changed; } });
    return { ...deps, send: useStdoutToPython().asyncStdoutToPython, get value() { return value; } };
}

for (const mode of ["missing", "false", "throw", "reject"]) test(`actual transport restores on ${mode} without a success notification`, async context => {
    context.mock.method(console, "error", () => {});
    const subject = await setup();
    if (mode !== "missing") subject.store.backend_subprocess = { write: () => {
        if (mode === "throw") throw Error("synchronous");
        return mode === "reject" ? Promise.reject(Error("rejected")) : Promise.resolve(false);
    } };
    assert.equal(await subject.send("/set/data/osc_port", 9001), false);
    assert.deepEqual(subject.value, { state: "ok", data: 9000 });
    assert.deepEqual(subject.notices.map(([key]) => key), ["common_error.request_send_failed"]);
});

test("successful transport preserves the wire format and stays pending until response", async () => {
    const subject = await setup(), writes = [];
    subject.store.backend_subprocess = { write: async line => { writes.push(line); } };
    assert.equal(await subject.send("/set/data/osc_port", 9001), true);
    assert.equal(writes.length, 1);
    assert.deepEqual(JSON.parse(writes[0]), { endpoint: "/set/data/osc_port", data: Buffer.from("9001").toString("base64") });
    assert.ok(writes[0].endsWith("\n"));
    assert.equal(subject.value.state, "pending");
    assert.deepEqual(subject.notices, []);
});

test("encoding throws also restore before any write", async context => {
    context.mock.method(console, "error", () => {});
    const subject = await setup(), cyclic = {};
    cyclic.self = cyclic;
    subject.store.backend_subprocess = { write: () => assert.fail("encoding should fail before write") };
    assert.equal(await subject.send("/set/data/osc_port", cyclic), false);
    assert.equal(subject.value.state, "ok");
});

test("backend-stopped notice is not duplicated by subsequent failed sends", async () => {
    const subject = await setup();
    subject.store.backend_stopped = true;
    assert.equal(await subject.send("/set/data/osc_port", 9001), false);
    assert.equal(subject.value.state, "ok");
    assert.deepEqual(subject.notices, []);
});

test("rejected language admission does not fail or release the existing owner", async () => {
    const subject = await setup();
    subject.store.rejectLanguage = true;
    assert.equal(await subject.send("/set/data/selected_target_languages", {}), false);
    assert.deepEqual(subject.events.map(([type]) => type), ["begin"]);
});

test("language preserves uncertain-write versus before-send failure semantics", async context => {
    context.mock.method(console, "error", () => {});
    for (const childExists of [false, true]) {
        const subject = await setup();
        if (childExists) subject.store.backend_subprocess = { write: async () => { throw Error("unknown delivery"); } };
        assert.equal(await subject.send("/set/data/selected_target_languages", {}), false);
        assert.deepEqual(subject.events.map(([type]) => type), ["begin", childExists ? "unconfirmed" : "before-send"]);
    }
});

test("failed shutdown does not suppress a subsequent unexpected exit notice", async () => {
    const subject = await setup();
    subject.store.backend_subprocess = { write: async () => false };
    assert.equal(await subject.send("/run/shutdown"), false);
    assert.equal(subject.store.backend_session.expectedExits.size, 0);
});

for (const endpoint of ["/run/update_software", "/run/update_cuda_software"]) {
    test(`${endpoint} arms this session before writing and disarms on transport failure`, async context => {
        context.mock.method(console, "error", () => {});
        for (const outcome of [true, false, "throw"]) {
            const subject = await setup(), session = subject.store.backend_session;
            subject.store.backend_subprocess = { write: async () => {
                assert.equal(session.expectedExits.has(endpoint), true);
                if (outcome === "throw") throw Error("write failed");
                return outcome;
            } };
            assert.equal(await subject.send(endpoint), outcome === true);
            assert.equal(session.expectedExits.has(endpoint), outcome === true);
        }
    });

    test(`${endpoint} rejection before write completion cannot re-arm the exit latch`, async () => {
        const subject = await setup(), session = subject.store.backend_session;
        subject.store.backend_subprocess = { write: async () => {
            rejectExpectedExit(session, endpoint);
            return true;
        } };
        assert.equal(await subject.send(endpoint), true);
        assert.equal(session.expectedExits.size, 0);
    });
}

test("an old rejected write cannot change a replacement session or replay the request", async context => {
    context.mock.method(console, "error", () => {});
    const subject = await setup();
    let reject;
    subject.store.backend_subprocess = { write: () => new Promise((_, no) => { reject = no; }) };
    const send = subject.send("/run/update_software");
    const nextSession = { expectedExits: new Map() };
    subject.store.backend_session = nextSession;
    subject.store.backend_subprocess = { write: () => assert.fail("must never replay") };
    reject(Error("late failure"));
    assert.equal(await send, false);
    assert.equal(nextSession.expectedExits.size, 0);
    assert.deepEqual(subject.notices, []);
});

test("overlapping update writes that both fail leave no expected exit", async () => {
    const subject = await setup(), completions = [];
    subject.store.backend_subprocess = { write: () => new Promise(resolve => completions.push(resolve)) };
    const first = subject.send("/run/update_software"), second = subject.send("/run/update_software");
    completions[0](false);
    assert.equal(await first, false);
    assert.equal(subject.store.backend_session.expectedExits.has("/run/update_software"), true);
    completions[1](false);
    assert.equal(await second, false);
    assert.equal(subject.store.backend_session.expectedExits.size, 0);
});
