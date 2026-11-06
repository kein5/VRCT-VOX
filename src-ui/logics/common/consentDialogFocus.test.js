import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals } from "../test/hookHarness.js";
import * as legacyConsent from "../configs/legacyModelConsent.js";
import * as endpointPrivacy from "./endpointPrivacy.js";

const boxes = new URL("../../views/app/config_page/setting_section/setting_box/", import.meta.url);
const entry = { id: "reviewed-model", name: "Reviewed model", target: "rvc", total_bytes: 100,
    provider: "Provider", license: "MIT", notice: "permissive", source: "https://example.test/model",
    licenses: [], artifacts: [], destination: "/models/reviewed", kind: "whisper", weight_type: "base",
    repo: "test/model", revision: "pinned-revision", manifest_version: "pinned-manifest" };

async function fixture(context, kind, openerState) {
    const runtime = hooks(), calls = [], focus = [], order = [];
    const control = name => ({ isConnected: true, disabled: false, tabIndex: 0,
        getAttribute: () => null, closest: () => null, focus: () => focus.push(name) });
    const fallbackControl = control("nearby control");
    const scope = { ...control("model group"), tabIndex: -1, querySelectorAll: () => [fallbackControl] };
    const section = { ...control("model section"), tabIndex: -1, querySelectorAll: () => [fallbackControl] };
    const opener = { ...control("opener"), closest: () => scope };
    stubGlobals(context, { document: { activeElement: opener } });
    const modal = { open: false, showModal() { this.open = true; },
        close() { this.open = false; order.push("close"); } };
    const dialogHooks = await loadModule(new URL("./useConsentDialog.js", import.meta.url), runtime);
    const downloads = { catalog: { models: [{ ...entry, target: kind === "ocr" ? "ocr" : "rvc" }],
        legacy_models: [entry], catalog_version: "reviewed-catalog" }, state: { jobs: {} }, hardware: {}, send: (endpoint, data) => {
        calls.push([endpoint, data]);
        if (endpoint.startsWith("/run/")) order.push("request");
    } };
    let ended = false;
    const end = () => { assert.equal(modal.open, false, "close() precedes unmount"); ended = true; order.push("unmount"); };
    const imports = {
        "@tauri-apps/api/core": { isTauri: () => false },
        "@tauri-apps/plugin-opener": { openUrl: () => assert.fail("no link activation") },
        "../../../../../../logics/common/endpointPrivacy": endpointPrivacy,
        "../../../../../../logics/common/useConsentDialog": dialogHooks,
        "../../../../../../../logics/common/useConsentDialog": dialogHooks,
        "../../../../../../logics/voice/useModelDownloads": { useModelDownloads: () => downloads },
        "../../../../../../../logics/voice/useModelDownloads": { useModelDownloads: () => downloads },
        "../../../../../../logics/voice/modelHardwareAdvice": { modelAdvice: () => ({}) },
        "../../../../../../../logics/configs/legacyModelConsent": legacyConsent,
        "../_components/env_readout/EnvReadout": { EnvReadout: "readout" },
        "../../../../../../logics/configs/ctranslate2License": {},
        "@logics_configs": {}, "../_templates/Templates": {}, "../_components": {},
        "../_components/compute_device/ComputeDevice": {}, "../_components/setup_section/SetupSection": {},
        "../_components/description/Description": {},
        "../_components/credential_pair/CredentialPair": {},
        "../_components/download_models/LegacyModelDownloadDialog": {}, "../shared_items/SharedItems": {},
        "@ui_configs": {}, "@logics_common": {},
    };
    const paths = { catalog: ["advanced_settings/ModelDownloads.jsx", "ModelDownloads"],
        ocr: ["ocr/OcrModels.jsx", "OcrModels"], nllb: ["translation/Translation.jsx", "CTranslate2LicenseDialog"],
        legacy: ["_components/download_models/LegacyModelDownloadDialog.jsx", "LegacyModelDownloadDialog"] };
    const [path, name] = paths[kind];
    const Component = (await loadModule(new URL(path, boxes), runtime, imports))[name];
    const props = kind === "catalog" ? { targets: ["rvc"] } : kind === "ocr"
        ? { ids: [entry.id], missing: [entry.id], onChanged: () => {}, title: "OCR models" }
        : kind === "nllb" ? { weight: entry, action: "select", fallback: { current: section },
            onCancel: end, onConfirm: () => { calls.push(["select"]); end(); } }
        : { kind: "whisper", weightType: "base", onCancel: end, onDownload: data => calls.push(["download", data]) };
    const render = () => runtime.render(Component, props, tree => {
        const dialog = find(tree, node => node.type === "dialog");
        if (dialog) dialog.ref.current = modal;
        if (tree.type === "section") tree.ref.current = section;
    });
    context.after(() => runtime.unmount());
    let tree = render();
    if (["catalog", "ocr"].includes(kind)) {
        find(tree, node => node.type === "button" && node.props.children === "model_downloads.review").props.onClick();
    }
    tree = render();
    const commit = async () => {
        if (openerState === "removed") opener.isConnected = false;
        if (openerState === "disabled") opener.disabled = true;
        if (ended) runtime.unmount();
        else {
            assert.equal(modal.open, false, "close() precedes the render that removes the dialog");
            assert.equal(find(render(), node => node.type === "dialog"), null);
        }
        await Promise.resolve();
    };
    return { render, tree, modal, calls, focus, order, commit, runtime, scope, opener, fallbackControl };
}

for (const kind of ["catalog", "ocr", "nllb", "legacy"]) {
    for (const path of ["back/cancel", "start/consent", "escape"]) {
        for (const openerState of ["present", "removed", "disabled"]) {
            test(`${kind}: ${path} closes before unmount and restores focus (${openerState} opener)`, async context => {
                const s = await fixture(context, kind, openerState);
                let tree = s.tree;
                const start = () => find(tree, node => node.type === "button" &&
                    ["model_downloads.start", "config_page.translation.ctranslate2_weight_type.confirm_select"].includes(node.props.children));
                assert.equal(s.modal.open, true);
                assert.equal(start().props.disabled, true);
                start().props.onClick(); // A disabled handler cannot bypass consent.
                assert.equal(s.calls.filter(([endpoint]) => !endpoint.startsWith("/get/")).length, 0);
                if (path === "start/consent") {
                    find(tree, node => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } });
                    tree = s.render();
                    assert.equal(start().props.disabled, false);
                    assert.equal(s.calls.filter(([endpoint]) => !endpoint.startsWith("/get/")).length, 0);
                    start().props.onClick();
                } else if (path === "escape") {
                    let prevented = false;
                    find(tree, node => node.type === "dialog").props.onCancel({ preventDefault: () => { prevented = true; } });
                    assert.equal(prevented, true);
                } else find(tree, node => node.type === "button" && node.props.autoFocus).props.onClick();
                assert.equal(s.modal.open, false);
                await s.commit();
                assert.deepEqual(s.focus, [openerState === "present" ? "opener" : "nearby control"]);
                assert.equal(s.order.filter(event => event === "close").length, 1);
                const writes = s.calls.filter(([endpoint]) => !endpoint.startsWith("/get/"));
                assert.equal(writes.length, path === "start/consent" ? 1 : 0);
                if (path === "start/consent" && ["catalog", "ocr"].includes(kind)) {
                    assert.deepEqual(writes[0], ["/run/start_model_download", { id: entry.id, consent: true, catalog_version: "reviewed-catalog" }]);
                }
            });
        }
    }
}

test("a pending download with no enabled nearby control returns focus to its named section", async context => {
    const s = await fixture(context, "catalog", "disabled");
    s.fallbackControl.disabled = true;
    find(s.tree, node => node.type === "button" && node.props.autoFocus).props.onClick();
    await s.commit();
    assert.deepEqual(s.focus, ["model section"]);
});

test("NLLB falls back to the labelled section when its template has no enabled controls", async context => {
    const s = await fixture(context, "nllb", "disabled");
    s.fallbackControl.disabled = true;
    find(s.tree, node => node.type === "button" && node.props.autoFocus).props.onClick();
    await s.commit();
    assert.deepEqual(s.focus, ["model section"]);
});

test("removing the entire model row uses a control in the stable section", async context => {
    const s = await fixture(context, "ocr", "removed");
    s.scope.isConnected = false;
    find(s.tree, node => node.type === "button" && node.props.autoFocus).props.onClick();
    await s.commit();
    assert.deepEqual(s.focus, ["nearby control"]);
});
