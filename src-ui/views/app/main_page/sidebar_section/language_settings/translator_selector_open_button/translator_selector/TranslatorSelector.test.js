import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../../logics/test/hookHarness.js";

test("an unavailable translation engine cannot be selected with the keyboard and leaves the tab order", async () => {
    const runtime = hooks(), selected = [], closed = [];
    const { TranslatorSelector } = await loadModule(new URL("./TranslatorSelector.jsx", import.meta.url), runtime, {
        "@utils": { chunkArray: (items, size) => Array.from({ length: Math.ceil(items.length / size) }, (_, i) => items.slice(i * size, i * size + size)) },
        "@store": { useStore_IsOpenedTranslatorSelector: () => ({ updateIsOpenedTranslatorSelector: value => closed.push(value) }) },
        "@logics_main": { useLanguageSettings: () => ({ canChangeLanguageSettings: () => true, isLanguageSettingsBusy: false,
            setSelectedTranslationEngines: id => selected.push(id) }) },
    });
    const engines = [
        { id: "CTranslate2", label: "CTranslate2", is_available: true, is_default: true },
        { id: "DeepL_API", label: "DeepL API", is_available: false },
    ];
    const tree = runtime.render(TranslatorSelector, { selected_id: "CTranslate2", translation_engines: engines, is_selected_same_language: false });
    const box = id => {
        const node = find(tree, item => item.type?.name === "TranslatorBox" && item.props.id === id);
        return runtime.render(node.type, node.props);
    };
    const press = (element, key) => element.props.onKeyDown({ key, repeat: false, preventDefault() {} });

    const unavailable = box("DeepL_API");
    assert.equal(unavailable.props.tabIndex, -1);
    assert.equal(unavailable.props["aria-disabled"], true);
    for (const key of ["Enter", " "]) press(unavailable, key);
    unavailable.props.onClick();
    assert.deepEqual(selected, []);
    assert.deepEqual(closed, []);

    const available = box("CTranslate2");
    assert.equal(available.props.tabIndex, 0);
    assert.equal(available.props["aria-disabled"], false);
    press(available, "Enter");
    assert.deepEqual(closed, [false]);
});
