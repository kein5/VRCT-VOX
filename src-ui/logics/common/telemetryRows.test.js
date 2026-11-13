import assert from "node:assert/strict";
import { test } from "node:test";
import { telemetryRows, sentSummary } from "./telemetryRows.js";

// i18next's behaviour for the two ways this file calls it: a known key resolves (here, to
// itself plus its values), an unknown one falls back to defaultValue.
const KNOWN = new Set(["telemetry_contents.events.app_started", "telemetry_contents.events.error",
    "telemetry_contents.gpu_kind.gpu", "telemetry_contents.gpu_kind.igpu", "telemetry_contents.gpu_driver",
    "telemetry_contents.fields.hw_gpu"]);
const t = (key, options = {}) => {
    if (!KNOWN.has(key) && !key.startsWith("telemetry_contents.fields.")) return options.defaultValue ?? key;
    const values = Object.entries(options).filter(([name]) => name !== "defaultValue").map(([name, value]) => `${name}=${value}`);
    return values.length ? `${key}(${values.join(",")})` : key;
};

const EVENT = {
    event: "app_started", v: 2, timestamp: "2026-11-13T15:58:00Z", app_version: "0.1.0-beta.6", os: "Windows",
    os_version: "10.0.26320", locale: "ja-JP",
    hw: { cpu: "12th Gen Intel(R) Core(TM) i7-1255U", cores: 12, ram_gb: 32, gpus: [
        { name: "Intel(R) Iris(R) Xe Graphics", kind: "igpu", vram_gb: 16, driver: "32.0.101.7085" },
        { name: "NVIDIA GeForce RTX 3060 Ti", kind: "gpu", vram_gb: 8, driver: "32.0.16.2124" }] },
};

test("an event reads as one row for each thing it holds", () => {
    const rows = telemetryRows(EVENT, t);
    assert.deepEqual(rows.map(row => [row.label, row.value]), [
        ["telemetry_contents.fields.event", "telemetry_contents.events.app_started"],
        ["telemetry_contents.fields.v", "2"],
        // The timestamp as it is sent: ISO 8601 in UTC.
        ["telemetry_contents.fields.timestamp", "2026-11-13T15:58:00Z"],
        ["telemetry_contents.fields.app_version", "0.1.0-beta.6"],
        ["telemetry_contents.fields.os", "Windows"],
        ["telemetry_contents.fields.os_version", "10.0.26320"],
        ["telemetry_contents.fields.locale", "ja-JP"],
        ["telemetry_contents.fields.hw_cpu", "12th Gen Intel(R) Core(TM) i7-1255U"],
        ["telemetry_contents.fields.hw_cores", "12"],
        ["telemetry_contents.fields.hw_ram_gb", "32 GB"],
        ["telemetry_contents.fields.hw_gpu(number=1)",
            "Intel(R) Iris(R) Xe Graphics / telemetry_contents.gpu_kind.igpu / 16 GB / telemetry_contents.gpu_driver(version=32.0.101.7085)"],
        ["telemetry_contents.fields.hw_gpu(number=2)",
            "NVIDIA GeForce RTX 3060 Ti / telemetry_contents.gpu_kind.gpu / 8 GB / telemetry_contents.gpu_driver(version=32.0.16.2124)"],
    ]);
    assert.equal(new Set(rows.map(row => row.key)).size, rows.length);
    const error = telemetryRows({ ...EVENT, event: "error", error_code: "speech_server_out_of_memory" }, t);
    assert.deepEqual(error.at(-1), { key: "error_code", label: "telemetry_contents.fields.error_code", value: "speech_server_out_of_memory" });
});

test("a field this list does not know is shown as it is, never left out", () => {
    const rows = telemetryRows({
        event: "session_summary", timestamp: "2026-11-13T09:15:00Z", features: { tts: true }, note: "plain",
        hw: { tpm: "2.0", gpus: [{ name: "GPU", bus: "thunderbolt", kind: "egpu" }, "not an object"], cores: 8 },
    }, t);
    assert.deepEqual(rows.map(row => [row.label, row.value]), [
        // An event kind and a GPU kind without a translation keep their own names.
        ["telemetry_contents.fields.event", "session_summary"],
        ["telemetry_contents.fields.timestamp", "2026-11-13T09:15:00Z"],
        ["features", "{\"tts\":true}"],
        ["note", "plain"],
        ["hw.tpm", "2.0"],
        ["telemetry_contents.fields.hw_gpu(number=1)", "GPU / egpu / bus: thunderbolt"],
        ["telemetry_contents.fields.hw_gpu(number=2)", "not an object"],
        ["telemetry_contents.fields.hw_cores", "8"],
    ]);
    for (const nothing of [null, undefined, "text", [EVENT]]) assert.deepEqual(telemetryRows(nothing, t), []);
    // Hardware that is not an object is still shown.
    assert.deepEqual(telemetryRows({ hw: "RTX" }, t).map(row => [row.label, row.value]), [["hw", "RTX"]]);
});

test("a sent event is summed up by its kind and its error code", () => {
    assert.equal(sentSummary(EVENT, t), "telemetry_contents.events.app_started");
    assert.equal(sentSummary({ event: "error", error_code: "VRAM_ERROR" }, t), "telemetry_contents.events.error (VRAM_ERROR)");
    assert.equal(sentSummary({ event: "later_kind" }, t), "later_kind");
});
