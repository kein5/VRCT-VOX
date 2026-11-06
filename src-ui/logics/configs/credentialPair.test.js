import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, stubGlobals, eventTarget, find } from "../test/hookHarness.js";
import { flush, loadBridgeRoutes } from "../test/bridgeHarness.js";
import { rebaseDraft } from "../voice/draftRebase.js";
import { changedPaths } from "../voice/saveBar.js";
import { createSettingsWriteResponses } from "../common/settingsWriteResponses.js";
import { endpointDescription } from "../common/endpointPrivacy.js";

const providers = [["OpenAICompatible", "openai_compatible", "translation"], ["CustomWhisper", "custom_whisper", "transcription"]];
async function setup(context, base, provider, section) {
    context.mock.timers.enable({ apis: ["setTimeout"] });
    const runtime = hooks(), requests = [], owners = createSettingsWriteResponses();
    // Flush state updates as React would; a render that keeps rebasing a fresh
    // saved object must fail here instead of hiding an effect/render loop.
    const useState = runtime.api.useState;
    let updates = 0;
    runtime.api.useState = initial => {
        const [value, setValue] = useState(initial);
        return [value, next => setValue(previous => {
            const resolved = typeof next === "function" ? next(previous) : next;
            if (!Object.is(previous, resolved)) updates++;
            return resolved;
        })];
    };
    context.after(() => { runtime.unmount(); owners.stop(); });
    stubGlobals(context, { window: eventTarget() });
    let entry;
    const draft = await loadModule(new URL("../voice/useSettingsDraft.jsx", import.meta.url), runtime, {
        "./draftRebase": { rebaseDraft }, "./saveBar": { changedPaths, setSaveBarEntry: (_, value) => { entry = value; } },
    });
    const settings = {
        [`current${base}URL`]: { state: "ok", data: "https://provider-a.example/v1" },
        [`current${base}AuthKey`]: { state: "ok", data: "FAKE-KEY-A" },
    };
    const component = await loadModule(new URL("../../views/app/config_page/setting_section/setting_box/_components/credential_pair/CredentialPair.jsx", import.meta.url), runtime, {
        "../../../../../../../logics/voice/useSettingsDraft": draft,
        "../../../../../../../logics/common/endpointPrivacy": { endpointDescription },
        "../../_templates/Templates": { EntryWithSaveButtonContainer: "url", AuthKeyContainer: "key" },
        "@useStdoutToPython": { useStdoutToPython: () => ({ asyncStdoutToPython: (endpoint, data) => {
            const request = owners.begin(endpoint);
            requests.push({ endpoint, data, request });
            return request.response;
        } }) },
    });
    const render = () => {
        for (let count = 0; count < 20; count++) {
            const previous = updates;
            const tree = runtime.render(component.CredentialPair, { settings, base, provider, section });
            if (updates === previous) return tree;
        }
        assert.fail("credential form did not settle after 20 renders");
    };
    const field = type => find(render(), node => node.type === type).props;
    const edit = (type, value) => { field(type).onChangeFunction(value); render(); };
    render();
    return { requests, owners, edit, field, render, settings, entry: () => entry };
}

for (const [base, provider, section] of providers) {
    for (const enter of [false, true]) test(`${provider}: ${enter ? "Enter" : "shared Save"} submits both edited credentials once`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit("url", "https://provider-b.example/v1");
        s.edit("key", "FAKE-KEY-B");
        assert.equal(s.entry().changes.length, 2);
        if (enter) s.field("key").saveFunction();
        else s.entry().save();
        s.render();
        assert.equal(s.requests.length, 1);
        const request = s.requests[0];
        assert.equal(request.endpoint, `/set/data/${provider}_auth_key_and_url`);
        assert.deepEqual(request.data, { url: "https://provider-b.example/v1", auth_key: "FAKE-KEY-B" });
        s.owners.receive({ endpoint: `/get/data/${provider}_url`, status: 200, result: request.data.url });
        assert.equal(s.entry().saving, true);
        s.settings[`current${base}URL`].data = request.data.url;
        s.settings[`current${base}AuthKey`].data = request.data.auth_key;
        s.owners.receive({ endpoint: request.endpoint, status: 200, result: request.data });
        await flush(); s.render();
        assert.equal(s.entry().saveState, "saved");
        assert.equal(s.entry().dirty, false);
    });

    for (const [field, value, suffix, data] of [
        ["key", "FAKE-KEY-B", "auth_key", "FAKE-KEY-B"],
        ["key", "", "auth_key", undefined],
    ]) test(`${provider}: editing only ${field} (${value || "delete"}) preserves the single-field endpoint`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit(field, value); s.entry().save(); s.render();
        assert.equal(s.requests.length, 1);
        assert.equal(s.requests[0].endpoint, `/${value ? "set" : "delete"}/data/${provider}_${suffix}`);
        assert.equal(s.requests[0].data, data);
    });

    test(`${provider}: a changed URL clears the saved key and blocks every save path`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit("url", "https://provider-b.example/v1");
        assert.equal(s.field("key").variable, "");
        assert.equal(s.entry().canSave, false);
        assert.deepEqual(s.field("key").add_warnings, [{ label: "config_page.common.credential_reentry_required" }]);
        s.field("url").saveFunction(); s.field("key").saveFunction(); s.entry().save();
        await flush(); s.render();
        assert.equal(s.requests.length, 0);
        s.edit("key", "   ");
        assert.equal(s.entry().canSave, false);
        s.field("key").saveFunction();
        assert.equal(s.requests.length, 0);
    });

    test(`${provider}: trimmed URL comparison restores an untouched key`, async context => {
        const s = await setup(context, base, provider, section);
        const savedURL = s.settings[`current${base}URL`].data;
        s.edit("url", `  ${savedURL}  `);
        assert.equal(s.field("key").variable, "FAKE-KEY-A");
        s.edit("url", "https://provider-b.example/v1");
        s.edit("url", "https://provider-c.example/v1");
        assert.equal(s.field("key").variable, "");
        s.edit("url", `  ${savedURL}  `);
        assert.equal(s.field("key").variable, "FAKE-KEY-A");
        assert.equal(s.entry().canSave, true);
        assert.deepEqual(s.field("key").add_warnings, []);
    });

    for (const value of ["FAKE-KEY-A", "FAKE-KEY-B"]) {
        for (const keyFirst of [false, true]) test(`${provider}: URL edits preserve a typed ${value} (key first: ${keyFirst})`, async context => {
            const s = await setup(context, base, provider, section);
            if (keyFirst) s.edit("key", value);
            s.edit("url", "https://provider-b.example/v1");
            if (!keyFirst) s.edit("key", value);
            s.edit("url", s.settings[`current${base}URL`].data);
            assert.equal(s.field("key").variable, value);
            s.edit("url", "https://provider-c.example/v1");
            assert.equal(s.field("key").variable, value);
            assert.equal(s.entry().canSave, true);
            s.field("key").saveFunction(); s.render();
            assert.equal(s.requests.length, 1);
            const request = s.requests[0];
            assert.equal(request.endpoint, `/set/data/${provider}_auth_key_and_url`);
            assert.deepEqual(request.data, { url: "https://provider-c.example/v1", auth_key: value });
            s.settings[`current${base}URL`].data = request.data.url;
            s.settings[`current${base}AuthKey`].data = value;
            s.owners.receive({ endpoint: request.endpoint, status: 200, result: request.data });
            await flush(); s.render();
            assert.equal(s.entry().dirty, false);
            s.edit("url", "https://provider-d.example/v1");
            assert.equal(s.field("key").variable, "");
        });
    }

    for (const leave of [false, true]) test(`${provider}: ${leave ? "leave dialog" : "Discard"} restores both values and resets key entry`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit("url", "https://provider-b.example/v1");
        assert.equal(s.field("key").variable, "");
        // A refresh must not reinsert the saved secret into the edited pair.
        s.settings[`current${base}AuthKey`] = { state: "ok", data: "FAKE-KEY-A" };
        s.render();
        assert.equal(s.field("key").variable, "");
        if (leave) {
            let proceeded = false, prevented = false;
            window.dispatch("vrct:settings-leave", {
                preventDefault: () => { prevented = true; }, detail: { proceed: () => { proceeded = true; } },
            });
            const dialog = find(s.render(), node => node.type === "dialog");
            assert.equal(prevented, true);
            find(dialog, node => node.type === "button" && node.props.children === "voice_ui.keep_editing").props.onClick();
            assert.equal(s.field("key").variable, "");
            assert.equal(proceeded, false);
            window.dispatch("vrct:settings-leave", { preventDefault() {}, detail: { proceed: () => { proceeded = true; } } });
            find(s.render(), node => node.type === "button" && node.props.children === "voice_ui.discard_leave").props.onClick();
            assert.equal(proceeded, true);
        } else s.entry().discard();
        s.render();
        assert.equal(s.field("url").variable, s.settings[`current${base}URL`].data);
        assert.equal(s.field("key").variable, "FAKE-KEY-A");
        assert.equal(s.entry().dirty, false);
        s.edit("key", "FAKE-KEY-B"); s.entry().discard(); s.render();
        s.edit("url", "https://provider-c.example/v1");
        assert.equal(s.field("key").variable, "");
        assert.equal(s.requests.length, 0);
    });

    test(`${provider}: deleting the saved key permits a later URL-only save`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit("key", ""); s.entry().save(); s.render();
        const deletion = s.requests[0];
        assert.equal(deletion.endpoint, `/delete/data/${provider}_auth_key`);
        s.settings[`current${base}AuthKey`].data = null;
        s.owners.receive({ endpoint: deletion.endpoint, status: 200, result: null });
        await flush(); s.render();
        s.edit("url", "https://provider-b.example/v1");
        assert.equal(s.entry().canSave, true);
        s.entry().save(); s.render();
        assert.equal(s.requests[1].endpoint, `/set/data/${provider}_url`);
        assert.equal(s.requests[1].data, "https://provider-b.example/v1");
    });

    test(`${provider}: rebasing a refreshed saved key keeps the new URL draft empty`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit("url", "https://provider-b.example/v1");
        s.settings[`current${base}AuthKey`].data = "FAKE-REFRESHED-KEY";
        s.render();
        assert.equal(s.field("key").variable, "");
        assert.equal(s.field("url").variable, "https://provider-b.example/v1");
        assert.equal(s.entry().canSave, false);
        s.entry().discard(); s.render();
        assert.equal(s.field("key").variable, "FAKE-REFRESHED-KEY");
        assert.equal(s.entry().dirty, false);
    });

    for (const failure of ["rejected", "transport"]) test(`${provider}: ${failure} pair remains editable without sending a fallback key`, async context => {
        const s = await setup(context, base, provider, section);
        s.edit("url", "https://provider-b.example/v1"); s.edit("key", "FAKE-KEY-B");
        s.entry().save(); s.render();
        const request = s.requests[0];
        if (failure === "transport") s.owners.fail(request.request, true);
        else s.owners.receive({ endpoint: request.endpoint, status: 400, result: { error_code: "auth_failed", data: "FAKE-KEY-A" } });
        await flush(); s.render();
        assert.equal(s.field("url").variable, "https://provider-b.example/v1");
        assert.equal(s.field("key").variable, "FAKE-KEY-B");
        assert.equal(s.entry().dirty, true);
        assert.equal(s.entry().saveState, "save_failed");
        assert.equal(s.requests.length, 1);
    });

    test(`${provider}: pair response updates both confirmed fields in the receive bridge`, async () => {
        const s = await loadBridgeRoutes();
        s.receiveRoutes({ endpoint: `/set/data/${provider}_auth_key_and_url`, status: 200,
            result: { url: "https://provider-b.example/v1", auth_key: "FAKE-KEY-B" } });
        assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry[`Atom_${base}URL`]),
            { state: "ok", data: "https://provider-b.example/v1" });
        assert.deepEqual(s.runtime.store.get(s.stores.dynamicStoreRegistry[`Atom_${base}AuthKey`]),
            { state: "ok", data: "FAKE-KEY-B" });
        assert.deepEqual(s.notices, []);
    });
}
