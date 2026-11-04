import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { hooks, loadModule, find } from "../../../../../../logics/test/hookHarness.js";
import * as helpers from "../../../../../../logics/configs/ocrReadiness.js";

const windowRegion = { x: 0.6, y: 0.1, width: 0.2, height: 0.2 };
const vrRegion = { x: 0.1, y: 0.5, width: 0.3, height: 0.4 };
const prefix = "config_page.ocr.";

async function setup(t, status) {
    t.mock.timers.enable({ apis: ["setInterval"] });
    const runtime = hooks(), sent = [], polled = [];
    const value = data => ({ data, state: "ok" });
    const ocr = {
        currentOcrCaptureStatus: value(status),
        getOcrCaptureStatus: () => polled.push("initial"),
        currentOcrCaptureRegion: value(windowRegion),
        currentOcrVrCaptureRegion: value(vrRegion),
        setOcrCaptureRegion: region => sent.push(["window", region]),
        setOcrVrCaptureRegion: region => sent.push(["vr", region]),
    };
    const imports = {
        "@logics_configs": { useOcr: () => ocr },
        "@useI18n": { useI18n: () => ({ t: (key, params) => params?.status ? `${key} ${params.status}` : key }) },
        "../../../../../../logics/configs/ocrReadiness": helpers,
        "../_templates/Templates": { SliderContainer: "slider" },
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
    };
    const components = await loadModule(new URL("./OcrRegions.jsx", import.meta.url), runtime, imports);
    const { OcrStatus } = await loadModule(new URL("./OcrStatus.jsx", import.meta.url), runtime, imports);
    t.after(() => runtime.unmount());
    return { ...components, runtime, ocr, sent, polled,
        render: () => runtime.render(components.OcrRegions),
        status: (props = {}) => runtime.render(OcrStatus, props),
        editor: (source, tree) => find(tree, node => node.type === components.OcrRegionEditor && node.props.source === source),
    };
}

test("region editors share capture status without polling or adding a second readout", async t => {
    const s = await setup(t, { active: true, source: "window", available_sources: ["window", "vr"] });
    for (const source of ["window", "vr", null]) {
        s.ocr.currentOcrCaptureStatus.data.source = source;
        const tree = s.render();
        assert.equal(find(tree, node => node.type === "readout"), null);
        assert.deepEqual(s.editor("window", tree).props.variable.data, windowRegion);
        assert.deepEqual(s.editor("vr", tree).props.variable.data, vrRegion);
    }
    t.mock.timers.tick(3000);
    assert.deepEqual(s.polled, []);
    assert.deepEqual(s.sent, []);
});

test("one live readout combines the source and runtime, including failure and recovery", async t => {
    const s = await setup(t, null);
    const readiness = { engine: true, language_supported: true, missing_models: [], capture: "ok" };
    const render = () => s.status({ readiness });
    assert.equal(render().props.children.props.children, `${prefix}capture_source.checking`);
    for (const source of ["window", "vr", null]) {
        for (const state of ["waiting", "reading", "retrying", "reading"]) {
            s.ocr.currentOcrCaptureStatus.data = { active: true, source, state, stage: "detector" };
            const tree = render();
            assert.equal(tree.type, "readout");
            assert.equal(tree.props.children.props.role, "status");
            const message = `${prefix}runtime.${state === "retrying" ? "failed_detector" : state}`;
            assert.equal(tree.props.children.props.children, source ? `${prefix}capture_source.${source} ${message}` : message);
            assert.equal(tree.props.tone, state === "retrying" ? "failed" : state === "reading" ? "active" : "warning");
        }
    }
    s.ocr.currentOcrCaptureStatus.data = { active: false, state: "stopped", source: null };
    assert.equal(render().props.children.props.children, `${prefix}capture_source.stopped ${prefix}readiness.ready`);
    readiness.capture = "window_not_found";
    assert.equal(render().props.children.props.children, `${prefix}capture_source.stopped ${prefix}readiness.window_not_found`);
    assert.deepEqual(s.sent, []);
});

test("edits and reset use the source's own setter, including when that source is inactive", async t => {
    const s = await setup(t, { active: true, source: "vr", available_sources: ["window", "vr"] });
    const tree = s.render();
    for (const source of ["window", "vr"]) {
        const region = source === "window" ? windowRegion : vrRegion;
        const editor = s.runtime.render(s.OcrRegionEditor, s.editor(source, tree).props);
        assert.equal(editor.props["aria-label"], `${prefix}region.${source}_label`);
        find(editor, node => node.type === "slider" && node.props.label === `${prefix}region.width`)
            .props.setterFunction(10);
        assert.deepEqual(s.sent.at(-1), [source, { ...region, width: 0.1 }]);
        find(editor, node => node.type === "button").props.onClick();
        assert.deepEqual(s.sent.at(-1), [source, helpers.FULL_REGION]);
        const preview = find(editor, node => node.props?.role === "img");
        assert.deepEqual(preview.props.children.props.style, {
            left: `${region.x * 100}%`, top: `${region.y * 100}%`,
            width: `${region.width * 100}%`, height: `${region.height * 100}%`,
        });
    }
});

test("Linux shows only the window region, even if a VR region was saved on Windows", async t => {
    const s = await setup(t, { active: true, source: "window", available_sources: ["window"] });
    const tree = s.render();
    assert.ok(s.editor("window", tree));
    assert.equal(s.editor("vr", tree), null);
    assert.equal(find(tree, node => node.props?.children === `${prefix}region.source_switch`), null);
    s.ocr.currentOcrCaptureStatus.data = null;
    assert.equal(s.editor("vr", s.render()), null);
});

test("status polling uses the current getter, starts once, and stops when the page closes", async t => {
    const s = await setup(t, null);
    s.status();
    s.render(); // The sibling region editor shares the reply without another poll.
    assert.deepEqual(s.polled, ["initial"]);
    s.ocr.getOcrCaptureStatus = () => s.polled.push("new");
    s.status();
    t.mock.timers.tick(1000);
    assert.deepEqual(s.polled, ["initial", "new"]);
    t.mock.timers.tick(2000);
    assert.deepEqual(s.polled, ["initial", "new", "new", "new"]);
    s.runtime.unmount();
    t.mock.timers.tick(5000);
    assert.deepEqual(s.polled, ["initial", "new", "new", "new"]);
    assert.deepEqual(s.sent, []);
});

test("the refresh button still requests readiness without changing settings", async t => {
    const s = await setup(t, null);
    const refreshed = [];
    const tree = s.status({ onRefresh: () => refreshed.push(true) });
    tree.props.actions.props.onClick();
    assert.deepEqual(refreshed, [true]);
    assert.deepEqual(s.polled, ["initial"]);
    assert.deepEqual(s.sent, []);
});

test("reset is disabled while pending or already full", async t => {
    const s = await setup(t, null);
    for (const variable of [{ data: windowRegion, state: "pending" }, { data: helpers.FULL_REGION, state: "ok" }]) {
        const tree = s.runtime.render(s.OcrRegionEditor, { source: "vr", variable, setRegion: () => {} });
        assert.equal(find(tree, node => node.type === "button").props.disabled, true);
    }
});

test("English and Japanese have source status and separate region labels", async () => {
    for (const language of ["en", "ja"]) {
        const text = await readFile(new URL(`../../../../../../../locales/${language}.yml`, import.meta.url), "utf8");
        const ocr = text.slice(text.indexOf("    ocr:"));
        assert.match(ocr, /^\s+capture_source:\n/m);
        for (const key of ["checking", "stopped", "window", "vr", "window_label",
            "vr_label", "source_switch", "vr_desc", "vr_reset", "vr_preview_label"]) {
            assert.match(ocr, new RegExp(`^\\s+${key}: \\S`, "m"), `${language}: ${key}`);
        }
    }
});
