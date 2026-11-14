// Pure helpers for Config → Chat reading: the reading region and the readiness summary.
// The backend validates the region again (config.py); these keep the sliders consistent.

export const FULL_REGION = Object.freeze({ x: 0, y: 0, width: 1, height: 1 });
export const MIN_REGION_SIDE = 0.02;
const KEYS = ["x", "y", "width", "height"];

const finite = (value, fallback) => (Number.isFinite(Number(value)) ? Number(value) : fallback);
const round = value => Math.round(value * 10000) / 10000;

export const normalizeRegion = region => {
    const source = region && typeof region === "object" ? region : FULL_REGION;
    let x = Math.min(Math.max(finite(source.x, 0), 0), 1 - MIN_REGION_SIDE);
    let y = Math.min(Math.max(finite(source.y, 0), 0), 1 - MIN_REGION_SIDE);
    const width = Math.min(Math.max(finite(source.width, 1), MIN_REGION_SIDE), 1 - x);
    const height = Math.min(Math.max(finite(source.height, 1), MIN_REGION_SIDE), 1 - y);
    return { x: round(x), y: round(y), width: round(width), height: round(height) };
};

// One slider moved (value in percent). Moving an edge keeps the area inside the
// window by shrinking the size first, then (for a size) clamping to what is left.
export const withRegionValue = (region, key, percent) => {
    if (!KEYS.includes(key)) throw new Error(`unknown region key: ${key}`);
    const current = normalizeRegion(region);
    const value = finite(percent, 0) / 100;
    const next = { ...current, [key]: value };
    if (key === "x") next.width = Math.min(current.width, 1 - Math.min(value, 1 - MIN_REGION_SIDE));
    if (key === "y") next.height = Math.min(current.height, 1 - Math.min(value, 1 - MIN_REGION_SIDE));
    return normalizeRegion(next);
};

export const regionPercent = (region, key) => Math.round(normalizeRegion(region)[key] * 1000) / 10;

export const isFullRegion = region => {
    const r = normalizeRegion(region);
    return r.x === 0 && r.y === 0 && r.width === 1 && r.height === 1;
};

// The first thing still blocking chat reading, as an i18n key and params.
export const readinessSummary = readiness => {
    if (!readiness) return { key: "config_page.ocr.readiness.checking", params: {}, ok: false };
    if (readiness.engine === false) return { key: "config_page.ocr.readiness.engine_unavailable", params: {}, ok: false };
    if (readiness.language_supported === false) return { key: "config_page.ocr.readiness.language_unsupported", params: {}, ok: false };
    if ((readiness.missing_models ?? []).length > 0) return { key: "config_page.ocr.readiness.models_missing", params: {}, ok: false };
    if (readiness.capture === "capture_unavailable") return { key: "config_page.ocr.readiness.capture_unavailable", params: {}, ok: false };
    if (readiness.capture === "window_not_found") {
        return { key: "config_page.ocr.readiness.window_not_found", params: { title: readiness.window_title ?? "VRChat" }, ok: false };
    }
    return { key: "config_page.ocr.readiness.ready", params: {}, ok: true };
};

export const runtimeSummary = runtime => {
    if (!runtime || runtime.state === "stopped") return null;
    // Linux: the window the user shared is gone and none is found by name. Say what to do
    // instead of the general capture failure.
    const lost = runtime.state === "retrying" && runtime.stage === "capture" && runtime.shared_window === "ended";
    const state = lost ? "shared_window_ended" : runtime.state === "retrying"
        ? `failed_${["capture", "detector", "recognition"].includes(runtime.stage) ? runtime.stage : "tick"}`
        : runtime.state === "reading" ? "reading" : "waiting";
    const tone = runtime.state === "retrying" ? "failed" : state === "reading" ? "active" : "warning";
    return { key: `config_page.ocr.runtime.${state}`, params: {}, ok: state === "reading", tone };
};

// Installation, preference and the worker's adopted detector are separate facts.
// `enabled` is the switch as the page knows it (it may be newer than the readiness reply).
export const detectorStatus = (readiness, enabled, runtime = readiness?.runtime) => {
    if (!readiness || typeof readiness.detector_model !== "string") return null;
    const installed = readiness.detector_installed === true;
    const preferred = (enabled ?? readiness.detector_enabled) !== false;
    const running = runtime && runtime.state !== "stopped";
    const adopted = running && runtime.detector === "vrct-vox-chatbox";
    const on = !!adopted && runtime.state === "reading";
    const state = adopted ? on ? "on" : "paused"
        : !installed ? "missing" : !preferred ? "off" : running ? "restart" : "ready";
    return { model: readiness.detector_model, installed, on, preferred, key: `config_page.ocr.detector.status_${state}` };
};

// One readout combines the worker's actual source and runtime state. Readiness
// describes how to start when stopped; it cannot override a running failure.
export const captureStatusSummary = (status, readiness) => {
    if (!status) return { key: "config_page.ocr.capture_source.checking", tone: "neutral" };
    if (!status.active || status.state === "stopped") {
        const summary = readinessSummary(readiness);
        return { ...summary, sourceKey: "config_page.ocr.capture_source.stopped", tone: summary.ok ? "neutral" : "warning" };
    }
    // A shared window is still the "window" source; the label tells which window is read.
    const source = status.source === "window" && status.shared_window === "active" ? "shared" : status.source;
    const sourceKey = ["window", "vr", "shared"].includes(source) ? `config_page.ocr.capture_source.${source}` : null;
    return { ...runtimeSummary(status), sourceKey };
};
