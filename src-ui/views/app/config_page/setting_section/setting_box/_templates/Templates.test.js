import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../logics/test/hookHarness.js";

const base = "../_components/";
const all = (tree, predicate) => {
    const result = [];
    find(tree, node => { if (predicate(node)) result.push(node); return false; });
    return result;
};
async function setup() {
    const runtime = hooks();
    const { LabelComponent } = await loadModule(new URL(base + "label_component/LabelComponent.jsx", import.meta.url), hooks(), {
        "../_atoms/_open_webpage_button/_OpenWebpageButton": { _OpenWebpageButton: "webpage" },
        "../description/Description": { Description: "description" },
    });
    const { RadioButton } = await loadModule(new URL(base + "radio_button/RadioButton.jsx", import.meta.url), hooks());
    const { DownloadModels } = await loadModule(new URL(base + "download_models/DownloadModels.jsx", import.meta.url), hooks(), {
        "../index": { RadioButton }, "../_atoms/_download_button/_DownloadButton": { _DownloadButton: "download" },
    });
    const { DropdownMenu, MultiDropdownMenu } = await loadModule(new URL(base + "dropdown_menu/DropdownMenu.jsx", import.meta.url), hooks(), {
        "../_atoms/_dropdown_menu/_DropdownMenu": { _DropdownMenu: "dropdown" },
    });
    const components = { LabelComponent, RadioButton, DownloadModels, DropdownMenu, MultiDropdownMenu,
        Entry: "entry", EntryWithSaveButton: "save-entry", AuthKey: "auth", ColorEntryWithSaveButton: "color",
        Slider: "slider", SwitchBox: "switch", WordFilter: "word-filter", WordFilterListToggleComponent: "word-toggle",
        HotkeysEntry: "hotkey", ActionButton: "action", MessageFormat: "message", ConnectionCheckButton: "check" };
    const templates = await loadModule(new URL("./Templates.jsx", import.meta.url), runtime, {
        "@store": { useStore_IsBreakPoint: () => ({ currentIsBreakPoint: { data: false } }) },
        "../_components": components, "@common_components": { Checkbox: "checkbox" },
    });
    const render = (name, props) => {
        let tree = runtime.render(templates[name], props);
        if (tree.type.name === "CommonContainer") tree = runtime.render(tree.type, tree.props);
        return tree;
    };
    return { runtime, templates, components, render };
}

for (const name of ["Checkbox", "Entry", "EntryWithSaveButton", "AuthKey", "ColorEntryWithSaveButton", "Slider", "SwitchBox", "DropdownMenu", "RadioButton", "DownloadModels", "ActionButton", "HotkeysEntry", "ConnectionCheckButton"]) {
    test(`${name} template connects description and warning IDs without changing its label`, async () => {
        const s = await setup();
        const props = { label: "Setting", desc: "Help", add_warnings: [{ label: "Unavailable" }], "aria-describedby": "existing-help" };
        const tree = s.render(`${name}Container`, props);
        const label = find(tree, node => node.type === s.components.LabelComponent);
        const control = tree.props.children[1];
        const renderedLabel = label.type(label.props);
        const help = find(renderedLabel, node => node.type === "description");
        const warning = find(renderedLabel, node => node.props?.className === "warnings_section");
        assert.equal(control.props["aria-describedby"], `existing-help ${help.props.id} ${warning.props.id}`);
        assert.equal(control.props["aria-labelledby"], find(renderedLabel, node => node.props?.children === "Setting").props.id);
        assert.equal(control.props.label, "Setting");
        const next = s.render(`${name}Container`, props).props.children[1];
        assert.equal(next.props["aria-describedby"], control.props["aria-describedby"]);
    });
}

for (const name of ["RadioButton", "DownloadModels"]) test(`${name} exposes a labelled radio group and keeps individual option labels`, async () => {
    const s = await setup();
    const tree = s.render(`${name}Container`, { label: "Recognition engine", desc: "Choose one", name: "engine",
        checked_variable: { state: "ok", data: "a" }, options: [{ id: "a", label: "Engine A", is_downloaded: true }] });
    const label = tree.props.children[0], control = tree.props.children[1];
    let group = control.type(control.props);
    if (name === "DownloadModels") { const radio = find(group, node => node.type === s.components.RadioButton); group = radio.type(radio.props); }
    assert.equal(group.props.role, "radiogroup");
    assert.equal(group.props["aria-labelledby"], label.props.label_id);
    assert.equal(group.props["aria-describedby"], label.props.description_id);
    assert.ok(find(group, node => node.type === "label"));
    assert.equal(find(group, node => node.type === "input").props.name, "engine");
});

test("multi-select row has a group label and each dropdown receives the shared help", async () => {
    const s = await setup();
    const tree = s.render("MultiDropdownMenuContainer", { label: "Compute device", desc: "Help", dropdown_settings: [
        { dropdown_id: "device", secondary_label: "Device" }, { dropdown_id: "type", secondary_label: "Type" },
    ] });
    const label = tree.props.children[0], control = tree.props.children[1], group = control.type(control.props);
    assert.equal(group.props.role, "group");
    assert.equal(group.props["aria-labelledby"], label.props.label_id);
    for (const dropdown of all(group, node => node.type === s.components.DropdownMenu)) {
        const atom = find(dropdown.type(dropdown.props), node => node.type === "dropdown");
        assert.equal(atom.props["aria-describedby"], label.props.description_id);
        assert.ok(["Device", "Type"].includes(atom.props.secondary_label));
    }
});

for (const name of ["WordFilter", "MessageFormat"]) test(`${name} shares one label and description across its two rows`, async () => {
    const s = await setup();
    const tree = s.runtime.render(s.templates[`${name}Container`], { label: "Setting", desc: "Help" });
    const rows = tree.props.children.map(row => s.runtime.render(row.type, row.props));
    const label = find(rows[0], node => node.type === s.components.LabelComponent);
    const control = find(rows[1], node => node.type === s.components[name]);
    assert.equal(control.props["aria-labelledby"], label.props.label_id);
    assert.equal(control.props["aria-describedby"], label.props.description_id);
});

test("FormRow preserves a field's error relation while adding its description", async () => {
    const runtime = hooks();
    const { FormRow } = await loadModule(new URL(base + "form_row/FormRow.jsx", import.meta.url), runtime, {
        "../description/Description": { Description: "description" },
    });
    const child = runtime.api.createElement("textarea", { "aria-describedby": "error", "aria-invalid": true });
    const tree = runtime.render(FormRow, { label: "Instructions", description: "Help", children: child });
    const input = find(tree, node => node.type === "textarea"), description = find(tree, node => node.type === "description");
    assert.equal(input.props["aria-describedby"], `error ${description.props.id}`);
    assert.equal(input.props["aria-invalid"], true);
    assert.equal(find(tree, node => node.type === "label").props.htmlFor, input.props.id);
});
