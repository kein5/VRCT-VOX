import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find, stubGlobals, eventTarget } from "../../../../logics/test/hookHarness.js";

async function fixture(context) {
    const runtime = hooks(), focus = [], changes = [];
    let opened = "overlay", dropdown = "";
    const control = name => ({ isConnected: true, disabled: false, tabIndex: 0,
        getAttribute: () => null, closest: () => null, matches: () => false,
        focus: () => focus.push(name) });
    const opener = control("opener"), fallbackControl = control("main control");
    const fallback = { current: { ...control("main page"), querySelectorAll: () => [fallbackControl] } };
    stubGlobals(context, { document: { ...eventTarget(), activeElement: opener }, HTMLElement: Object });
    const dialogHooks = await loadModule(new URL("../../../../logics/common/useConsentDialog.js", import.meta.url), runtime);
    const { ModalController } = await loadModule(new URL("./ModalController.jsx", import.meta.url), runtime, {
        "../../../../logics/common/useConsentDialog": dialogHooks,
        "@store": {
            useStore_OpenedQuickSetting: () => ({ currentOpenedQuickSetting: { data: opened },
                updateOpenedQuickSetting: value => { changes.push([value, modal.open]); opened = value; } }),
            useStore_IsOpenedDropdownMenu: () => ({ currentIsOpenedDropdownMenu: { data: dropdown } }),
        },
        "@setting_box": { Vr: "vr-settings", Updater: "update-settings" },
    });
    const modal = { open: false, opens: 0, showModal() { this.open = true; this.opens++; },
        close() { this.open = false; } };
    const render = () => runtime.render(ModalController, { fallback }, tree => {
        const dialog = find(tree, node => node.type === "dialog");
        if (dialog) dialog.ref.current = modal;
        const button = find(tree, node => node.type === "button");
        if (button?.ref) button.ref.current = control("close");
    });
    context.after(() => runtime.unmount());
    return { render, modal, focus, changes, opener, fallbackControl, runtime,
        setDropdown: value => { dropdown = value; }, setOpened: value => { opened = value; } };
}

test("quick settings uses a named native modal with initial close focus", async context => {
    const s = await fixture(context), tree = s.render();
    assert.equal(tree.type, "dialog", "native modal confines Tab/Shift+Tab and makes the background inert");
    assert.equal(tree.props["aria-label"], "config_page.vr.section_label_overlay");
    assert.equal(s.modal.open, true);
    assert.equal(s.modal.opens, 1);
    assert.equal(find(tree, node => node.type === "button").props.autoFocus, true);
    s.render();
    assert.equal(s.modal.opens, 1, "ordinary rerenders do not reopen the dialog");
});

for (const action of ["close button", "backdrop", "Escape"]) {
    for (const openerState of ["present", "removed", "disabled"]) {
        test(`quick settings: ${action} closes before unmount and restores focus (${openerState} opener)`, async context => {
            const s = await fixture(context), tree = s.render();
            if (openerState === "removed") s.opener.isConnected = false;
            if (openerState === "disabled") s.opener.disabled = true;
            if (action === "Escape") {
                let prevented = false;
                tree.props.onCancel({ preventDefault: () => { prevented = true; } });
                assert.equal(prevented, true);
            } else if (action === "backdrop") {
                find(tree, node => node.props?.className === "bg_onclick_close_area").props.onClick();
            } else find(tree, node => node.type === "button").props.onClick();
            assert.deepEqual(s.changes, [["", false]], "close the native dialog before removing its content");
            assert.equal(s.render(), null);
            await Promise.resolve();
            assert.deepEqual(s.focus, [openerState === "present" ? "opener" : "main control"]);
        });
    }
}

test("dropdown Escape prevents native cancellation but still reaches the dropdown listener", async context => {
    const s = await fixture(context);
    s.setDropdown("overlay-position");
    let tree = s.render(), prevented = false;
    const event = { key: "Escape", preventDefault: () => { prevented = true; },
        stopPropagation: () => assert.fail("the dropdown must receive Escape") };
    tree.props.onKeyDownCapture(event);
    assert.equal(prevented, true, "suppress the browser cancel before the dropdown clears its state");
    tree.props.onCancel(event);
    assert.deepEqual(s.changes, []);
    assert.equal(s.modal.open, true);
    s.setDropdown(""); // The existing document listener closes the dropdown.
    tree = s.render();
    prevented = false;
    tree.props.onKeyDownCapture(event);
    assert.equal(prevented, false);
    tree.props.onCancel(event);
    assert.deepEqual(s.changes, [["", false]]);
});

test("external dismissal returns focus to the main page when every fallback control is unavailable", async context => {
    const s = await fixture(context);
    s.render();
    s.opener.isConnected = false;
    s.fallbackControl.disabled = true;
    s.setOpened("");
    s.render();
    await Promise.resolve();
    assert.equal(s.modal.open, false);
    assert.deepEqual(s.focus, ["main page"]);
});
