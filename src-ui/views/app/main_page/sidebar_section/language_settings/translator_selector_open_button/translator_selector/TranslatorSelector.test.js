import assert from "node:assert/strict";
import { test } from "node:test";
import { hooks, loadModule, find } from "../../../../../../../logics/test/hookHarness.js";

const engines = [
    { id: "CTranslate2", label: "CTranslate2", is_available: true, is_default: true },
    { id: "DeepL_API", label: "DeepL API", is_available: false },
];

async function setup(selected = [], closed = []) {
    const runtime = hooks();
    const { TranslatorSelector } = await loadModule(new URL("./TranslatorSelector.jsx", import.meta.url), runtime, {
        "@utils": { chunkArray: (items, size) => Array.from({ length: Math.ceil(items.length / size) }, (_, i) => items.slice(i * size, i * size + size)) },
        "@store": { useStore_IsOpenedTranslatorSelector: () => ({ updateIsOpenedTranslatorSelector: value => closed.push(value) }) },
        "@logics_main": { useLanguageSettings: () => ({ canChangeLanguageSettings: () => true, isLanguageSettingsBusy: false,
            setSelectedTranslationEngines: id => selected.push(id) }) },
    });
    return { runtime, TranslatorSelector };
}

test("an unavailable translation engine cannot be selected with the keyboard and leaves the tab order", async () => {
    const selected = [], closed = [];
    const { runtime, TranslatorSelector } = await setup(selected, closed);
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

test("the reason an engine is unavailable is on screen and describes the group and the engine", async () => {
    const { runtime, TranslatorSelector } = await setup();
    const render = (translation_engines, is_selected_same_language = false) =>
        runtime.render(TranslatorSelector, { selected_id: "CTranslate2", translation_engines, is_selected_same_language });
    const group = tree => find(tree, item => item.props?.role === "group");
    const text = (tree, key) => find(tree, item => item.type === "p" && item.props.children === key);
    const box = (tree, id) => {
        const node = find(tree, item => item.type?.name === "TranslatorBox" && item.props.id === id);
        return runtime.render(node.type, node.props);
    };

    const tree = render(engines);
    const hint = text(tree, "main_page.translator_selector.unavailable_hint");
    assert.ok(hint);
    assert.equal(group(tree).props["aria-describedby"], hint.props.id);
    assert.equal(box(tree, "DeepL_API").props["aria-describedby"], hint.props.id);
    assert.equal(box(tree, "CTranslate2").props["aria-describedby"], undefined);

    const all_available = render(engines.map(engine => ({ ...engine, is_available: true })));
    assert.equal(text(all_available, "main_page.translator_selector.unavailable_hint"), null);
    assert.equal(group(all_available).props["aria-describedby"], undefined);

    // Choosing the same language has its own, more exact reason; it replaces the hint.
    const same_language = render(engines, true);
    assert.equal(text(same_language, "main_page.translator_selector.unavailable_hint"), null);
    const same_reason = text(same_language, "main_page.translator_selector.is_selected_same_language");
    assert.equal(group(same_language).props["aria-describedby"], same_reason.props.id);
    assert.equal(box(same_language, "DeepL_API").props["aria-describedby"], same_reason.props.id);
});
