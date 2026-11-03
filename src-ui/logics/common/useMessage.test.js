import assert from "node:assert/strict";
import { test } from "node:test";
import { loadModule } from "../test/hookHarness.js";
import { loadBridgeRoutes, deferred } from "../test/bridgeHarness.js";
import { keepRecentLogs } from "./messageLogLimit.js";

async function setup(send = async () => true) {
    let useMessage;
    const writes = [];
    const subject = await loadBridgeRoutes(async ({ runtime, stores }) => {
        ({ useMessage } = await loadModule(new URL("./useMessage.js", import.meta.url), runtime, {
            "@store": stores,
            "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: (...args) => {
                writes.push(args);
                return send(...args);
            } }) },
            "../transcription/useRealtimeASR": {}, "../transcription/realtimeCaptionState": {},
            "./messageLogLimit": { keepRecentLogs },
        }));
        return { useMessage };
    });
    return { ...subject, writes, message: subject.runtime.render(useMessage),
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
