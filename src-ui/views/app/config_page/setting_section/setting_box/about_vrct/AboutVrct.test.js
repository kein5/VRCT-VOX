import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import i18next from "i18next";
import yaml from "js-yaml";
import clsx from "clsx";
import { hooks, loadModule, find, stubGlobals, eventTarget } from "../../../../../../logics/test/hookHarness.js";

const resources = Object.fromEntries(await Promise.all(["en", "ja"].map(async language => [language, {
    translation: yaml.load(await readFile(new URL(`../../../../../../../locales/${language}.yml`, import.meta.url), "utf8")),
}])));
const all = (tree, predicate) => {
    const nodes = [];
    find(tree, node => { if (predicate(node)) nodes.push(node); return false; });
    return nodes;
};
const translate = async language => {
    const i18n = i18next.createInstance();
    await i18n.init({ lng: language, fallbackLng: false, resources });
    return { i18n, t: i18n.t.bind(i18n) };
};

for (const language of ["en", "ja"]) {
    test(`${language}: every About image link names its destination/person and credit images have text equivalents`, async () => {
        const translation = await translate(language), runtime = hooks();
        const source = await readFile(new URL("./AboutVrct.jsx", import.meta.url), "utf8");
        const images = Object.fromEntries([...source.matchAll(/from "(@images\/[^"]+)"/g)].map(match => [match[1], match[1]]));
        const { AboutVrct } = await loadModule(new URL("./AboutVrct.jsx", import.meta.url), runtime, {
            ...images, "@useI18n": { useI18n: () => translation },
            "@logics_configs": { useAppearance: () => ({ currentUiLanguage: { data: language } }) },
            "@logics_common": { useSoftwareVersion: () => ({ currentSoftwareVersion: { data: "test" } }) },
            "@ui_configs": { upstream_vrct_document_url: () => "https://example.test/docs" },
        });
        const tree = runtime.render(AboutVrct);
        const links = all(tree, node => node.props?.href_id);
        assert.equal(links.length, 12);
        const names = [];
        for (const component of links) {
            const link = component.type(component.props), name = link.props["aria-label"];
            assert.equal(link.type, "a"); assert.ok(link.props.href);
            assert.ok(name && !name.startsWith("config_page."));
            assert.equal(find(link, node => node.type === "img").props.alt, "");
            assert.equal(name, translation.t(`config_page.about_vrct.image_links.${component.props.href_id}`));
            names.push(name);
        }
        assert.equal(new Set(names).size, 12);
        const creditImages = all(tree, node => node.type === "img");
        assert.equal(creditImages.length, 15);
        for (const image of creditImages) {
            assert.ok(image.props.alt && !image.props.alt.startsWith("config_page."), image.props.src);
        }
        const disclaimer = find(tree, node => node.props?.className === "vrchat_disclaimer");
        // The trademark notice keeps its original English wording in every locale.
        assert.equal(disclaimer.props.lang, "en");
        assert.match(disclaimer.props.children, /not endorsed by VRChat/);
    });

    test(`${language}: color swatches identify the field and expose expansion`, async t => {
        const translation = await translate(language), runtime = hooks();
        stubGlobals(t, { document: eventTarget(), window: eventTarget() });
        const { ColorEntryWithSaveButton } = await loadModule(new URL("../_components/color_entry_with_save_button/ColorEntryWithSaveButton.jsx", import.meta.url), runtime, {
            clsx: { clsx }, "@useI18n": { useI18n: () => translation },
            "../_atoms/_entry/_Entry": { _Entry: "entry" }, "react-colorful": { HexColorPicker: "picker" },
        });
        const names = [];
        for (const label of language === "ja" ? ["文字色", "背景色"] : ["Text color", "Background color"]) {
            const tree = runtime.render(ColorEntryWithSaveButton, { label, variable: "#FFFFFF" });
            const button = find(tree, node => node.type === "button");
            assert.ok(button.props["aria-label"].includes(label));
            names.push(button.props["aria-label"]);
        }
        assert.equal(new Set(names).size, 2);
        let button = find(runtime.render(ColorEntryWithSaveButton, { label: "Field", variable: "#FFFFFF" }), node => node.type === "button");
        assert.equal(button.props["aria-expanded"], false);
        button.props.onClick();
        button = find(runtime.render(ColorEntryWithSaveButton, { label: "Field", variable: "#FFFFFF" }), node => node.type === "button");
        assert.equal(button.props["aria-expanded"], true);
        runtime.unmount();
    });

    test(`${language}: both VR duration sliders use localized visible and accessible values`, async () => {
        const translation = await translate(language), runtime = hooks();
        const settings = { opacity: 1, ui_scaling: 1, display_duration: 1, fadeout_duration: 2 };
        const controls = { ui_scaling: {}, display_duration: {}, fadeout_duration: {} };
        const { Vr } = await loadModule(new URL("../vr/Vr.jsx", import.meta.url), runtime, {
            "@useI18n": { useI18n: () => translation },
            "@ui_configs": { ui_configs: { overlay_small_log: controls } },
            "../_components": { Slider: "slider", SectionLabelComponent: "heading" },
            "../_templates/Templates": { RadioButtonContainer: "radio", CheckboxContainer: "checkbox", ActionButtonContainer: "action" },
            "@common_components": { ResetButton: "reset" }, "@utils": { randomIntMinMax: () => 0 },
            "@logics_configs": { useVr: () => ({ currentOverlaySmallLogSettings: { data: settings }, currentOverlayLargeLogSettings: {} }) },
        });
        const root = runtime.render(Vr);
        const overlay = find(root, node => node.props?.id === "overlay_settings_small");
        const overlayTree = overlay.type(overlay.props);
        const other = find(overlayTree, node => node.type?.name === "OtherControls");
        const tree = other.type(other.props);
        const durationSliders = all(tree, node => node.type === "slider" && [60, 5].includes(node.props.max));
        assert.equal(durationSliders.length, 2);
        for (const duration of durationSliders) {
            const sliderRuntime = hooks();
            const { Slider } = await loadModule(new URL("../_components/slider/Slider.jsx", import.meta.url), sliderRuntime, {
                "@logics_configs": { useSliderLogic: () => ({ ui_value: duration.props.variable }) },
            });
            const slider = sliderRuntime.render(Slider, duration.props);
            const thumb = find(slider, node => node.props?.role === "slider");
            const expected = translation.t("config_page.common.duration_seconds", { count: duration.props.variable });
            assert.equal(thumb.props["aria-valuetext"], expected);
            assert.equal(find(slider, node => node.props?.className === "valueLabelLabel").props.children, expected);
            assert.equal(expected, language === "ja" ? `${duration.props.variable}秒` : duration.props.variable === 1 ? "1 second" : "2 seconds");
        }
    });
}

test("all new locale keys exist in both files without relying on fallback", () => {
    const flatten = (value, prefix = "") => Object.entries(value).flatMap(([key, child]) => typeof child === "object"
        ? flatten(child, `${prefix}${key}.`) : [`${prefix}${key}`]);
    for (const language of ["en", "ja"]) {
        const page = resources[language].translation.config_page;
        const keys = [...flatten(page.about_vrct.image_links), ...flatten(page.about_vrct.credits)];
        const other = resources[language === "en" ? "ja" : "en"].translation.config_page;
        assert.deepEqual(keys, [...flatten(other.about_vrct.image_links), ...flatten(other.about_vrct.credits)]);
        for (const name of ["open_color_picker", "duration_seconds_one", "duration_seconds_other"]) assert.ok(page.common[name]);
        assert.ok(page.transcription.mic_word_filter.remove_word.includes("{{word}}"));
    }
});
