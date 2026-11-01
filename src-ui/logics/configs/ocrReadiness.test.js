import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { detectorStatus, FULL_REGION, isFullRegion, normalizeRegion, readinessSummary, regionPercent, withRegionValue } from "./ocrReadiness.js";

test("region stays inside the window whichever slider moves", () => {
    assert.deepEqual(normalizeRegion(null), FULL_REGION);
    assert.deepEqual(withRegionValue(FULL_REGION, "x", 50), { x: 0.5, y: 0, width: 0.5, height: 1 });
    assert.deepEqual(withRegionValue({ x: 0.5, y: 0, width: 0.5, height: 1 }, "width", 80), { x: 0.5, y: 0, width: 0.5, height: 1 });
    assert.deepEqual(withRegionValue(FULL_REGION, "height", 0), { x: 0, y: 0, width: 1, height: 0.02 });
    assert.deepEqual(withRegionValue(FULL_REGION, "y", 100), { x: 0, y: 0.98, width: 1, height: 0.02 });
    assert.equal(regionPercent({ x: 0.1234, y: 0, width: 0.5, height: 0.5 }, "x"), 12.3);
    assert.ok(isFullRegion(FULL_REGION));
    assert.ok(!isFullRegion({ x: 0, y: 0.1, width: 1, height: 0.9 }));
    assert.throws(() => withRegionValue(FULL_REGION, "z", 1));
});

test("garbage from the backend never produces an invalid region", () => {
    for (const value of [undefined, "x", { x: "a" }, { x: -1, y: 2, width: NaN, height: Infinity }]) {
        const region = normalizeRegion(value);
        assert.ok(region.x >= 0 && region.y >= 0);
        assert.ok(region.x + region.width <= 1 + 1e-9 && region.y + region.height <= 1 + 1e-9);
        assert.ok(region.width >= 0.02 && region.height >= 0.02);
    }
});

test("readiness reports the first blocking reason", () => {
    const ready = { engine: true, language_supported: true, missing_models: [], capture: "ok", window_title: "VRChat" };
    assert.equal(readinessSummary(null).key, "config_page.ocr.readiness.checking");
    assert.deepEqual(readinessSummary(ready), { key: "config_page.ocr.readiness.ready", params: {}, ok: true });
    assert.equal(readinessSummary({ ...ready, engine: false }).key, "config_page.ocr.readiness.engine_unavailable");
    assert.equal(readinessSummary({ ...ready, missing_models: ["ppocrv6-small"], capture: "window_not_found" }).key,
        "config_page.ocr.readiness.models_missing");
    assert.deepEqual(readinessSummary({ ...ready, capture: "window_not_found", window_title: "VRChat2" }).params, { title: "VRChat2" });
    assert.equal(readinessSummary({ ...ready, capture: "capture_unavailable" }).key, "config_page.ocr.readiness.capture_unavailable");
});

test("the chatbox detector is optional and its switch only counts once it is downloaded", () => {
    const base = { engine: true, language_supported: true, missing_models: [], capture: "ok",
        detector_model: "vrct-vox-chatbox-detector", detector_installed: false, detector_enabled: true };
    assert.equal(detectorStatus(null), null);
    assert.equal(detectorStatus({ engine: true }), null);  // an older backend without the detector
    assert.deepEqual(detectorStatus(base, true), { model: "vrct-vox-chatbox-detector", installed: false, on: false,
        key: "config_page.ocr.detector.status_missing" });
    assert.equal(readinessSummary(base).ok, true);  // not downloaded never blocks reading
    const installed = { ...base, detector_installed: true };
    assert.equal(detectorStatus(installed, true).key, "config_page.ocr.detector.status_on");
    assert.equal(detectorStatus(installed, false).key, "config_page.ocr.detector.status_off");
    // The page's switch wins over an older readiness reply; without it, readiness decides.
    assert.equal(detectorStatus({ ...installed, detector_enabled: false }, true).on, true);
    assert.equal(detectorStatus({ ...installed, detector_enabled: false }).on, false);
    assert.equal(detectorStatus(installed).on, true);
});

test("every readiness and OCR start-error string exists in English and Japanese", () => {
    const keys = ["checking", "ready", "engine_unavailable", "language_unsupported", "models_missing",
        "window_not_found", "capture_unavailable"].map(name => `config_page.ocr.readiness.${name}`);
    keys.push(...["engine_unavailable", "model_load_failed", "unsupported_language", "model_missing", "window_not_found",
        "capture_unavailable", "unknown"].map(name => `common_error.ocr_${name}`));
    keys.push("model_downloads.notice_ppocr", "config_page.ocr.region.label", "config_page.ocr.chatbox_filter.label",
        "config_page.ocr.models.title", "model_downloads.notice_chatbox",
        ...["label", "desc", "models_title", "optional", "status_on", "status_off", "status_missing"]
            .map(name => `config_page.ocr.detector.${name}`));
    for (const language of ["en", "ja"]) {
        const strings = yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
        for (const key of keys) {
            const value = key.split(".").reduce((node, part) => node?.[part], strings);
            assert.equal(typeof value, "string", `${language}: ${key}`);
            assert.ok(value.trim().length > 0, `${language}: ${key}`);
        }
    }
});
