import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Children } from "react";
import i18next from "i18next";
import yaml from "js-yaml";
import { hooks, loadModule, find, stubGlobals } from "../test/hookHarness.js";
import { loadBridgeRoutes } from "../test/bridgeHarness.js";
import * as consentLogic from "./legacyModelConsent.js";

const componentURL = new URL("../../views/app/config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog.jsx", import.meta.url);
const entry = { kind: "ctranslate2", weight_type: "nllb-200-distilled-600M-ct2-int8", name: "CTranslate2 NLLB 600M",
    provider: "JustFrederik", repo: "JustFrederik/nllb-200-distilled-600M-ct2-int8", license: "CC-BY-NC-4.0",
    non_commercial: true, total_bytes: 642903406, tokenizer_size_unknown: true,
    revision: "pinned-weight-commit", manifest_version: "reviewed-manifest",
    tokenizer: { repo: "facebook/nllb-200-distilled-600M", revision: "pinned-tokenizer-commit" } };

const whisper = { kind: "whisper", weight_type: "base", name: "Whisper base", provider: "Systran",
    repo: "Systran/faster-whisper-base", license: "MIT", non_commercial: false,
    total_bytes: 147882941, tokenizer: null, tokenizer_size_unknown: false,
    revision: "c".repeat(40), manifest_version: "reviewed-whisper-manifest" };

async function dialogFixture(context, language, reviewedEntry) {
    const translations = i18next.createInstance();
    const resource = yaml.load(readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8"));
    await translations.init({ lng: language, resources: { [language]: { translation: resource } } });
    const events = { focused: 0, opened: 0, closed: 0 };
    stubGlobals(context, { document: { activeElement: { isConnected: true, getAttribute: () => null,
        closest: () => null, focus: () => events.focused++ } } });
    const runtime = hooks(), requests = [], reads = [];
    const dialogHooks = await loadModule(new URL("../common/useConsentDialog.js", import.meta.url), runtime);
    const downloads = { catalog: { legacy_models: [reviewedEntry] }, send: (...args) => reads.push(args) };
    const { LegacyModelDownloadDialog } = await loadModule(componentURL, runtime, {
        "@useI18n": { useI18n: () => ({ t: translations.t.bind(translations) }) },
        "@tauri-apps/api/core": { isTauri: () => false },
        "@tauri-apps/plugin-opener": { openUrl: () => { throw new Error("No links should open in this test"); } },
        "../../../../../../../logics/voice/useModelDownloads": { useModelDownloads: () => downloads },
        "../../../../../../../logics/configs/legacyModelConsent": consentLogic,
        "../../../../../../../logics/common/useConsentDialog": dialogHooks,
    });
    const props = { kind: reviewedEntry.kind, weightType: reviewedEntry.weight_type,
        onCancel: () => events.closed++, onDownload: data => requests.push(data) };
    const modal = { open: false, showModal() { this.open = true; events.opened++; }, close() { this.open = false; } };
    const render = () => runtime.render(LegacyModelDownloadDialog, props, tree => {
        find(tree, node => node.type === "dialog").ref.current = modal;
    });
    context.after(() => runtime.unmount());
    render();
    return { runtime, requests, reads, downloads, events, render, t: translations.t.bind(translations) };
}

for (const language of ["en", "ja"]) {
    for (const reviewedEntry of [entry, whisper]) {
        test(`${language} ${reviewedEntry.kind}: labelled facts, size, revisions and consent remain distinct`, async context => {
            const s = await dialogFixture(context, language, reviewedEntry);
            let tree = s.render();
            const rows = Children.toArray(find(tree, node => node.type === "dl").props.children);
            const label = key => s.t(`legacy_model_downloads.${key}`);
            const labels = rows.map(row => find(row, node => node.type === "dt").props.children);
            assert.deepEqual(labels, ["model", "provider", "license", "size",
                ...(reviewedEntry.tokenizer ? ["additional_files"] : []), "revision_label", "terms"].map(label));
            const fact = key => rows.find(row => find(row, node => node.type === "dt").props.children === label(key));
            const value = key => find(fact(key), node => node.type === "dd");
            assert.equal(value("model").props.children, reviewedEntry.name);
            assert.equal(value("provider").props.children, reviewedEntry.provider);
            assert.ok(renderToStaticMarkup(value("license")).includes(reviewedEntry.license));
            const expectedSize = reviewedEntry.tokenizer
                ? (language === "ja" ? "642,903,406 バイト（約 613 MB）" : "642,903,406 bytes (about 613 MB)")
                : (language === "ja" ? "147,882,941 バイト（約 141 MB）" : "147,882,941 bytes (about 141 MB)");
            assert.equal(value("size").props.children, expectedSize);
            const assertRevision = (container, full) => {
                const code = find(container, node => node.type === "code");
                assert.equal(code.props.children, full.slice(0, 12));
                assert.equal(code.props.title, full);
                assert.equal(code.props["aria-description"], full);
            };
            assertRevision(value("revision_label"), reviewedEntry.revision);
            const licenseWarning = find(value("license"), node => node.props?.role === "alert");
            if (reviewedEntry.tokenizer) {
                const extra = value("additional_files");
                assert.ok(renderToStaticMarkup(extra).includes(reviewedEntry.tokenizer.repo));
                assert.equal(find(extra, node => node.type === "p").props.children, label("plus_tokenizer"));
                assertRevision(extra, reviewedEntry.tokenizer.revision);
                assert.equal(licenseWarning.props.children, label("non_commercial"));
            } else {
                assert.equal(fact("additional_files"), undefined);
                assert.equal(licenseWarning, null);
                assert.ok(!renderToStaticMarkup(tree).includes(label("plus_tokenizer")));
            }
            const terms = find(value("terms"), node => node.type === "a");
            assert.ok(terms.props.href.includes(reviewedEntry.revision));
            const consent = find(tree, node => node.type === "label");
            assert.equal(Children.toArray(consent.props.children).at(-1), label(reviewedEntry.tokenizer
                ? "consent" : "consent_without_extra_files"));
            const start = () => find(tree, node => node.type === "button" && node.props.children === s.t("model_downloads.start"));
            assert.equal(start().props.disabled, true);
            start().props.onClick();
            assert.deepEqual(s.requests, []);
            assert.equal(s.events.opened, 1);
            assert.equal(s.reads[0][0], "/get/data/model_download_catalog");
            assert.equal(find(tree, node => node.type === "button" && node.props.autoFocus).props.children, s.t("model_downloads.back"));
            find(tree, node => node.type === "input").props.onChange({ target: { checked: true } });
            s.downloads.catalog = { legacy_models: [{ ...reviewedEntry, manifest_version: "unreviewed-manifest" }] };
            tree = s.render();
            tree = s.render();
            assert.equal(start().props.disabled, false);
            start().props.onClick(); start().props.onClick();
            assert.deepEqual(s.requests, [{ weight_type: reviewedEntry.weight_type, consent: true,
                manifest_version: reviewedEntry.manifest_version }]);
            assert.equal(s.events.closed, 1);
            s.runtime.unmount();
            await Promise.resolve();
            assert.equal(s.events.focused, 1);
        });
    }
    test(`${language}: Escape cancels without a download and a reopened review is unchecked`, async context => {
        const s = await dialogFixture(context, language, entry);
        let tree = s.render();
        find(tree, node => node.type === "input").props.onChange({ target: { checked: true } });
        tree = s.render();
        find(tree, node => node.type === "dialog").props.onCancel({ preventDefault() {} });
        s.runtime.unmount();
        await Promise.resolve();
        assert.equal(s.events.closed, 1);
        assert.equal(s.events.focused, 1);
        assert.deepEqual(s.requests, []);
        const reopened = await dialogFixture(context, language, entry);
        const reopenedTree = reopened.render();
        assert.equal(find(reopenedTree, node => node.type === "input").props.checked, false);
        assert.equal(find(reopenedTree, node => node.type === "button"
            && node.props.children === reopened.t("model_downloads.start")).props.disabled, true);
    });
}

test("large sizes use the list's GB convention and three significant digits", () => {
    const t = (key, values) => key.endsWith("exact_bytes") ? `${values.bytes} bytes` : `${values.bytes} (about ${values.size})`;
    assert.equal(consentLogic.legacyReviewSize({ total_bytes: 1529008357 }, t), "1,529,008,357 bytes (about 1.42 GB)");
});

for (const [kind, base] of [["whisper", "Whisper"], ["ctranslate2", "CTranslate2"]]) {
    test(`${kind}: the settings download handler sends the reviewed consent unchanged`, async () => {
        const runtime = hooks(), sent = [];
        const name = `${base}WeightTypeStatus`;
        const { useSettingsLogics } = await loadModule(new URL("./config_page_setter/useSettingsLogics.js", import.meta.url), runtime, {
            "@store": { getStoreHook: () => () => ({ [`current${name}`]: { data: [] }, [`update${name}`]: () => {} }) },
            "@logics_common": { useNotificationStatus: () => ({}) },
            "@utils": {}, "../../voice/saveBar": {},
            "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: (...args) => sent.push(args) }) },
        });
        const api = runtime.render(() => useSettingsLogics([{ Category: "test", Base_Name: name,
            base_endpoint_name: `${kind}_weight`, logics_template_id: "weight_download_status" }], "test"));
        const payload = consentLogic.legacyDownloadRequest({ ...entry, kind }, true);
        api.settings[`download${name}`](payload);
        assert.deepEqual(sent, [[`/run/download_${kind}_weight`, payload]]);
    });
    test(`${kind}: consent rejection clears only its pending row and shows a translated notice`, async () => {
        const subject = await loadBridgeRoutes();
        const atom = subject.stores.dynamicStoreRegistry[`Atom_${base}WeightTypeStatus`];
        assert.ok(atom);
        subject.runtime.store.set(atom, { state: "ok", data: [
            { id: "requested", is_pending: true, is_downloaded: false, progress: 0 },
            { id: "other", is_pending: true, is_downloaded: true, progress: 0.5 },
        ] });
        subject.receiveRoutes({ status: 400, endpoint: `/run/download_${kind}_weight`, result: {
            error_code: "WEIGHT_DOWNLOAD_CONSENT_REQUIRED", data: { kind, weight_type: "requested" },
        } });
        assert.deepEqual(subject.runtime.store.get(atom).data, [
            { id: "requested", is_pending: false, is_downloaded: false, progress: null },
            { id: "other", is_pending: true, is_downloaded: true, progress: 0.5 },
        ]);
        assert.equal(subject.notices[0].key, "backend_errors.WEIGHT_DOWNLOAD_CONSENT_REQUIRED");
        subject.receiveRoutes({ status: 400, endpoint: `/run/error_${kind}_weight`, result: {
            error_code: "WEIGHT_DOWNLOAD_CONSENT_REQUIRED", data: { kind, weight_type: "requested", startup: true },
        } });
        assert.equal(subject.notices[1].key, "legacy_model_downloads.startup_skipped");
    });
}

for (const [kind, base] of [["whisper", "Whisper"], ["ctranslate2", "CTranslate2"]]) {
    test(`${kind}: asynchronous failure clears only the failed weight and ignores a stale job`, async () => {
        const subject = await loadBridgeRoutes();
        const atom = subject.stores.dynamicStoreRegistry[`Atom_${base}WeightTypeStatus`];
        const original = [
            { id: "requested", job_id: "current", is_pending: true, is_downloaded: true, progress: 12 },
            { id: "other", job_id: "another", is_pending: true, is_downloaded: false, progress: 50 },
        ];
        subject.runtime.store.set(atom, { state: "ok", data: original });
        const fail = data => subject.receiveRoutes({
            status: 400, endpoint: `/run/error_${kind}_weight`,
            result: { error_code: `WEIGHT_${kind.toUpperCase()}_DOWNLOAD`, data },
        });
        fail({ weight_type: "requested", job_id: "previous", downloaded: false });
        assert.deepEqual(subject.runtime.store.get(atom).data, original);
        fail({ weight_type: "requested", job_id: "current", downloaded: false });
        assert.deepEqual(subject.runtime.store.get(atom).data, [
            { ...original[0], is_pending: false, is_downloaded: false, progress: null },
            original[1],
        ]);
    });

    test(`${kind}: verified completion accepts identified payload and ignores late progress`, async () => {
        const subject = await loadBridgeRoutes();
        const atom = subject.stores.dynamicStoreRegistry[`Atom_${base}WeightTypeStatus`];
        subject.runtime.store.set(atom, { state: "ok", data: [
            { id: "requested", is_pending: true, is_downloaded: false, progress: 12 },
            { id: "other", is_pending: true, is_downloaded: false, progress: 50 },
        ] });
        const endpoint = `/run/downloaded_${kind}_weight`;
        subject.receiveRoutes({ status: 200, endpoint,
            result: { weight_type: "requested", job_id: "job", downloaded: false } });
        assert.equal(subject.runtime.store.get(atom).data[0].is_downloaded, false);
        subject.receiveRoutes({ status: 200, endpoint,
            result: { weight_type: "requested", job_id: "job", downloaded: true } });
        subject.receiveRoutes({ status: 200, endpoint: `/run/download_progress_${kind}_weight`,
            result: { weight_type: "requested", job_id: "job", progress: 0.9 } });
        assert.deepEqual(subject.runtime.store.get(atom).data, [
            { id: "requested", is_pending: false, is_downloaded: true, progress: null },
            { id: "other", is_pending: true, is_downloaded: false, progress: 50 },
        ]);
    });
}

test("duplicate refusal keeps its original job pending; cross-process refusal clears the refused row", () => {
    const rows = [{ id: "base", is_pending: true, is_downloaded: false, progress: null }];
    const busy = { weight_type: "base", job_id: "rejected", reason: "download_busy" };
    assert.deepEqual(consentLogic.clearLegacyDownloadFailure(rows, { ...busy, active_job_id: "running" }), rows);
    assert.equal(consentLogic.clearLegacyDownloadFailure(rows, busy)[0].is_pending, false);
});

for (const language of ["en", "ja"]) {
    test(`${language}: bundled tokenizer shows that its bytes are included`, async context => {
        const reviewed = { ...entry, tokenizer_size_unknown: false,
            tokenizer: { repo: entry.repo, revision: entry.revision, bundled: true } };
        const subject = await dialogFixture(context, language, reviewed);
        const html = renderToStaticMarkup(subject.render());
        assert.ok(html.includes(subject.t("legacy_model_downloads.included_tokenizer")));
        assert.ok(!html.includes(subject.t("legacy_model_downloads.plus_tokenizer")));
    });
}
