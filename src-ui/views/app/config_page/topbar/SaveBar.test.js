import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { hooks, loadModule, find, eventTarget, stubGlobals } from "../../../../logics/test/hookHarness.js";

const t = (key, options) => options?.changes ? `${key}[${options.changes}]` : key;
async function bar(context, entries) {
    const runtime = hooks();
    // The leave guard listens on the window while there are edits.
    stubGlobals(context, { window: eventTarget() });
    const { SaveBar } = await loadModule(new URL("./Topbar.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t }) }, "@logics_common": {},
        "../../../../logics/voice/saveBar": { useSaveBarEntries: () => entries }, "../../others/stop_actions/StopActions": {},
    });
    const tree = runtime.render(SaveBar);
    runtime.unmount();
    return { status: find(tree, node => node.props?.role === "status").props.children,
        count: find(tree, node => node.props?.className === "count"),
        save: find(tree, node => node.type === "button" && node.props.className === "save").props };
}
const entry = values => ({ dirty: true, edited: true, saving: false, saveState: "unsaved", changes: [], canSave: true, save() {}, discard() {}, ...values });

test("a change the page proposes is named as what Save will apply, not as an unsaved edit", async context => {
    // The RVC page selecting RVC: nothing was edited, one thing is pending.
    const proposed = await bar(context, [entry({ edited: false, changes: ["Use RVC for direct voice"] })]);
    assert.equal(proposed.status, "voice_ui.applies_on_save[Use RVC for direct voice]");
    assert.equal(proposed.count, null, "no count of changes the user did not make");
    assert.equal(proposed.save.disabled, false, "Save still applies it");
});

test("an edit is still an unsaved change, alone or beside a proposal", async context => {
    const edited = await bar(context, [entry({ changes: ["Pitch"] })]);
    assert.match(edited.status, /^voice_ui\.unsaved/);
    assert.ok(edited.count);
    const both = await bar(context, [entry({ edited: false, changes: ["Use RVC for direct voice"] }), entry({ changes: ["Pitch"] })]);
    assert.match(both.status, /^voice_ui\.unsaved/);
    // Forms that do not tell edits from proposals count as edited, as before.
    const legacy = await bar(context, [entry({ edited: undefined, changes: ["Port"] })]);
    assert.match(legacy.status, /^voice_ui\.unsaved/);
});

test("saving and a failed save keep their own words; nothing dirty is saved", async context => {
    assert.match((await bar(context, [entry({ edited: false, saving: true, changes: ["x"] })])).status, /^voice_ui\.saving/);
    assert.match((await bar(context, [entry({ edited: false, saveState: "save_failed", changes: ["x"] })])).status, /^voice_ui\.save_failed/);
    assert.match((await bar(context, [entry({ dirty: false, edited: false })])).status, /^voice_ui\.saved/);
});

test("the wording exists in English and Japanese and names the change", () => {
    for (const language of ["en", "ja"]) {
        const strings = yaml.load(readFileSync(new URL(`../../../../../locales/${language}.yml`, import.meta.url), "utf8")).voice_ui;
        assert.match(strings.applies_on_save, /\{\{changes\}\}/);
        assert.equal(typeof strings.changes_separator, "string");
    }
});
