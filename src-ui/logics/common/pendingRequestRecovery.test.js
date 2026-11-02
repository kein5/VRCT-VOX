import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createPendingRequestRecovery, restorePendingValue, settingPendingControl, staticPendingControls, featureResyncReads, restoreDownloadPending, sendWithRecovery } from "./pendingRequestRecovery.js";

const setup = (spec = settingPendingControl({ base_endpoint_name: "osc_port", logics_template_id: "get_set" })) => {
    const recovery = createPendingRequestRecovery(), reads = [];
    let value = { state: "pending", data: 9000 };
    recovery.register({ ...spec, restore: () => {
        const next = restorePendingValue(value), changed = next !== value;
        value = next;
        return changed;
    } });
    return { recovery, reads, get value() { return value; }, send: endpoint => { reads.push(endpoint); return Promise.resolve(true); } };
};

for (const status of [404, 423, 500]) test(`${status} restores only the failed control; only 500 reads confirmed state`, () => {
    const subject = setup();
    let other = { state: "pending", data: true };
    subject.recovery.register({ endpoints: ["/set/disable/logger_feature"], restore: () => { other = restorePendingValue(other); } });
    subject.recovery.receive({ endpoint: "/set/data/osc_port", status }, subject.send);
    assert.deepEqual(subject.value, { state: "ok", data: 9000 });
    assert.equal(other.state, "pending");
    assert.deepEqual(subject.reads, status === 500 ? ["/get/data/osc_port"] : []);
});

test("success and feature-specific errors stay with their existing handlers", () => {
    const subject = setup();
    for (const status of [200, 400, 409, 348]) subject.recovery.receive({ endpoint: "/set/data/osc_port", status }, subject.send);
    assert.equal(subject.value.state, "pending");
    assert.deepEqual(subject.reads, []);
});

test("500 on a read, or failed resync transport, cannot loop or re-lock the control", async () => {
    for (const send of [() => false, () => { throw Error("sync"); }, () => Promise.reject(Error("async"))]) {
        const subject = setup();
        subject.recovery.receive({ endpoint: "/set/data/osc_port", status: 500 }, send);
        subject.recovery.receive({ endpoint: "/get/data/osc_port", status: 500 }, subject.send);
        assert.deepEqual(subject.value, { state: "ok", data: 9000 });
        assert.deepEqual(subject.reads, []);
    }
    await Promise.resolve();
});

test("no read endpoint is invented for runtime switches", () => {
    for (const name of ["TranslationStatus", "TranscriptionSendStatus", "TranscriptionReceiveStatus", "OcrCaptureStatus", "MicThresholdCheckStatus", "SpeakerThresholdCheckStatus"]) {
        for (const endpoint of staticPendingControls[name].endpoints) {
            const subject = setup(staticPendingControls[name]);
            subject.recovery.receive({ endpoint, status: 500 }, subject.send);
            assert.equal(subject.value.state, "ok");
            assert.deepEqual(subject.reads, []);
        }
    }
});

test("run connection checks use their actual get names", () => {
    for (const [base, name] of [["IsLMStudioConnected", "lmstudio"], ["IsOllamaConnected", "ollama"]]) {
        const subject = setup(staticPendingControls[base]);
        subject.recovery.receive({ endpoint: `/run/${name}_connection`, status: 500 }, subject.send);
        assert.deepEqual(subject.reads, [`/get/data/connected_${name}`]);
    }
});

test("delete and both toggle directions restore without synthesizing a success", () => {
    for (const [template, name, prefix] of [["get_set_delete", "deepl_auth_key", "/delete/data/"],
        ["toggle_enable_disable", "logger_feature", "/set/enable/"], ["toggle_enable_disable", "logger_feature", "/set/disable/"]]) {
        const subject = setup(settingPendingControl({ base_endpoint_name: name, logics_template_id: template }));
        subject.recovery.receive({ endpoint: prefix + name, status: 500 }, subject.send);
        assert.equal(subject.value.data, 9000);
        assert.equal(subject.value.state, "ok");
        assert.deepEqual(subject.reads, [`/get/data/${name}`]);
    }
});

test("transport false, sync throw and rejection restore, never resend", async context => {
    context.mock.method(console, "error", () => {});
    for (const failure of [() => false, () => { throw Error("sync"); }, () => Promise.reject(Error("async"))]) {
        const subject = setup();
        let calls = 0, failures = 0;
        assert.equal(await sendWithRecovery(() => { calls++; return failure(); }, () => {
            failures++;
            subject.recovery.failSend("/set/data/osc_port");
        }), false);
        assert.deepEqual(subject.value, { state: "ok", data: 9000 });
        assert.equal(calls, 1);
        assert.equal(failures, 1);
    }
});

test("successful send stays pending; elapsed time cannot release it", async context => {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const subject = setup();
    assert.equal(await sendWithRecovery(() => true, () => assert.fail("unexpected failure")), true);
    context.mock.timers.tick(600000);
    assert.equal(subject.value.state, "pending");
    assert.deepEqual(subject.reads, []);
});

test("process exit restores all pending atoms, preserving confirmed values and errors", () => {
    const subject = setup();
    let second = { state: "pending", data: { device: "confirmed" } };
    const failed = { state: "error", data: false };
    subject.recovery.register({ restore: () => { second = restorePendingValue(second); } });
    subject.recovery.stop();
    assert.deepEqual(subject.value, { state: "ok", data: 9000 });
    assert.deepEqual(second, { state: "ok", data: { device: "confirmed" } });
    assert.equal(restorePendingValue(failed), failed);
    subject.recovery.stop();
    assert.deepEqual(subject.reads, []);
});

test("language, voice and download generations are not registered as generic settings", () => {
    const download = settingPendingControl({ base_endpoint_name: "ctranslate2_weight", logics_template_id: "weight_download_status" });
    assert.equal(download.download, true);
    assert.equal(download.read, "/get/data/selectable_ctranslate2_weight_type_dict");
    const subject = setup();
    for (const endpoint of ["/set/data/selected_target_languages", "/run/enable_tts", "/run/stop_direct_voice", "/run/start_model_download"])
        subject.recovery.receive({ endpoint, status: 500 }, subject.send);
    assert.deepEqual(subject.reads, []);
    assert.equal(subject.value.state, "pending");
});

test("all configured recovery reads exist in Python mapping and have UI routes", () => {
    const mapping = readFileSync(new URL("../../../src-python/mainloop.py", import.meta.url), "utf8");
    const mappedEndpoints = new Set([...mapping.matchAll(/^\s*"([^"]+)"\s*:/gm)].map(match => match[1]));
    const settings = readFileSync(new URL("../configs/config_page_setter/ui_config_setter.js", import.meta.url), "utf8").split("for (const setting_data")[0];
    const routes = readFileSync(new URL("../useReceiveRoutes.js", import.meta.url), "utf8");
    for (const read of [...Object.values(staticPendingControls).map(control => control.read), ...Object.values(featureResyncReads)]) if (read) {
        assert.ok(mappedEndpoints.has(read), read);
        assert.ok(routes.includes(`endpoint: "${read}"`), read);
    }
    // Extract only the declarative settings fields; no React / Vite alias imports.
    for (const match of settings.matchAll(/logics_template_id: "([^"]+)"[^}]*?base_endpoint_name: "([^"]+)"/g)) {
        const { read } = settingPendingControl({ logics_template_id: match[1], base_endpoint_name: match[2] });
        if (read) assert.ok(mappedEndpoints.has(read), read);
        else assert.equal(mappedEndpoints.has(`/get/data/${match[2]}`), false, `Do not omit existing getter: ${match[2]}`);
    }
});

test("a late recovery GET cannot overwrite or release a newer write", () => {
    const subject = setup();
    subject.recovery.beginSend("/set/data/osc_port");
    subject.recovery.receive({ endpoint: "/set/data/osc_port", status: 500 }, subject.send);
    subject.recovery.beginSend("/set/data/osc_port");
    assert.equal(subject.recovery.acceptResponse("/get/data/osc_port"), false);
    assert.equal(subject.recovery.acceptResponse("/set/data/osc_port"), true);
});

test("two failing writes serialize recovery reads, then accept the current read", () => {
    const subject = setup();
    for (let i = 0; i < 2; i++) {
        subject.recovery.beginSend("/set/data/osc_port");
        subject.recovery.receive({ endpoint: "/set/data/osc_port", status: 500 }, subject.send);
    }
    assert.equal(subject.reads.length, 1);
    assert.equal(subject.recovery.acceptResponse("/get/data/osc_port"), false);
    assert.equal(subject.reads.length, 2);
    assert.equal(subject.recovery.acceptResponse("/get/data/osc_port"), true);
    assert.ok(subject.reads.every(endpoint => endpoint.startsWith("/get/")));
});

test("late failed sends do not release a newer generic request", () => {
    const subject = setup();
    const first = subject.recovery.beginSend("/set/data/osc_port");
    const second = subject.recovery.beginSend("/set/data/osc_port");
    assert.equal(subject.recovery.failSend("/set/data/osc_port", 8000, first), false);
    assert.equal(subject.value.state, "pending");
    assert.equal(subject.recovery.failSend("/set/data/osc_port", 8001, second), true);
    assert.equal(subject.value.data, 9000);
});

test("legacy download failure restores only its item and resyncs the actual downloaded dictionary", () => {
    const recovery = createPendingRequestRecovery(), reads = [];
    let value = { state: "ok", data: [
        { id: "small", is_pending: true, is_downloaded: false, progress: 12 },
        { id: "large", is_pending: true, is_downloaded: true, progress: 5 },
    ] };
    recovery.register({ ...settingPendingControl({ base_endpoint_name: "whisper_weight", logics_template_id: "weight_download_status" }),
        restore: request => { value = restoreDownloadPending(value, request); },
        stop: () => { value = restoreDownloadPending(value, undefined, true); } });
    recovery.receive({ endpoint: "/run/download_whisper_weight", status: 500, result: { data: { weight_type: "small" } } },
        read => { reads.push(read); return true; });
    assert.deepEqual(value.data[0], { id: "small", is_pending: false, is_downloaded: false, progress: null });
    assert.equal(value.data[1].is_pending, true);
    assert.deepEqual(reads, ["/get/data/selectable_whisper_weight_type_dict"]);
    recovery.stop();
    assert.deepEqual(value.data[1], { id: "large", is_pending: false, is_downloaded: true, progress: null });
});

test("failed send identifies a legacy download even with another weight outstanding", () => {
    const recovery = createPendingRequestRecovery();
    let value = { state: "ok", data: ["small", "large"].map(id => ({ id, is_pending: true, is_downloaded: false, progress: null })) };
    recovery.register({ ...settingPendingControl({ base_endpoint_name: "ctranslate2_weight", logics_template_id: "weight_download_status" }),
        restore: request => { value = restoreDownloadPending(value, request); } });
    const first = recovery.beginSend("/run/download_ctranslate2_weight");
    recovery.beginSend("/run/download_ctranslate2_weight");
    recovery.failSend("/run/download_ctranslate2_weight", { weight_type: "small", accept_non_commercial_license: true }, first);
    assert.equal(value.data[0].is_pending, false);
    assert.equal(value.data[1].is_pending, true);
});

test("terminal failures republish confirmed atoms for a VR-only pending control", () => {
    const recovery = createPendingRequestRecovery(), publications = [];
    recovery.register({ ...staticPendingControls.TranslationStatus,
        restore: (_request, _all, publish) => { publications.push(publish); return publish; } });
    recovery.receive({ endpoint: "/set/enable/translation", status: 404 }, () => assert.fail("no read exists"));
    assert.equal(recovery.failSend("/set/enable/translation"), true);
    assert.deepEqual(publications, [true, true]);
});

test("exit cancels queued recovery reads, including late send rejections", async () => {
    const subject = setup();
    let reject;
    subject.recovery.receive({ endpoint: "/set/data/osc_port", status: 500 }, () => new Promise((_, fail) => { reject = fail; }));
    subject.recovery.receive({ endpoint: "/set/data/osc_port", status: 500 }, subject.send);
    subject.recovery.stop();
    reject(Error("sidecar exited"));
    await Promise.resolve();
    assert.deepEqual(subject.reads, []);
});
