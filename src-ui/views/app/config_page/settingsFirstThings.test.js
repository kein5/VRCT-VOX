import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { hooks, loadModule, find } from "../../../logics/test/hookHarness.js";

const all = (tree, predicate, found = []) => { find(tree, node => { if (predicate(node)) found.push(node); return false; }); return found; };
const icon = name => Object.assign(() => null, { icon: name });

test("chat reading has a page of its own, and search lists it on both pages it is on", async () => {
    const runtime = hooks();
    let tab = "ocr";
    const pages = Object.fromEntries(["Device", "Tts", "Rvc", "Appearance", "Translation", "Transcription", "Vrchat", "Ocr",
        "AdvancedSettings", "Vr", "Hotkeys", "AboutVrct", "Updater"].map(name => [name, name]));
    const { SettingBox } = await loadModule(new URL("./setting_section/setting_box/SettingBox.jsx", import.meta.url), runtime, {
        "@store": { useStore_SelectedConfigTabId: () => ({ currentSelectedConfigTabId: { data: tab } }) }, "@setting_box": pages,
    });
    assert.equal(runtime.render(SettingBox).type, "Ocr");
    for (const id of ["vrchat", "others"]) { tab = id; assert.equal(runtime.render(SettingBox).type, "Vrchat"); }

    const search = await loadModule(new URL("../../../logics/configs/config_page_setter/_aux/useConfigSearch.js", import.meta.url), runtime, {
        "@store": {}, "@logics_configs": {}, "@ui_configs": {}, "@root/locales/config.js": {},
        "../../../transcription/useRealtimeASR": {}, "../../../common/languageNames.js": {}, "../../../voice/settingsNavigation": {},
    });
    assert.deepEqual(search.settingTabs("ocr", "source_language"), ["ocr", "vrchat"]);
    assert.deepEqual(search.settingTabs("others", "send_message_to_vrc"), ["vrchat"]);
    assert.deepEqual(search.settingTabs("others", "vrc_mic_mute_sync"), ["vrchat", "device"]);
    assert.deepEqual(search.settingTabs("translation", "deepl_auth_key"), ["translation"]);
});

test("the side menu lists chat reading after VRChat, with an icon of its own and a name in both languages", async () => {
    const runtime = hooks();
    const svg = name => (name.endsWith(".svg?react") ? icon(name) : name);
    const images = ["mic", "tts_speaker", "voice_conversion", "mui_palette", "translation", "mui_graphic_eq", "mui_head_mounted_device",
        "mui_keyboard_alt", "mui_code_blocks", "refresh", "chat_transcribe", "mui_document_scanner"];
    const sidebar = await loadModule(new URL("./sidebar_section/SidebarSection.jsx", import.meta.url), runtime, {
        "@store": { useStore_SelectedConfigTabId: () => ({ currentSelectedConfigTabId: { data: "device" }, updateSelectedConfigTabId() {} }),
            useStore_IsBreakPoint: () => ({ currentIsBreakPoint: { data: false } }) },
        ...Object.fromEntries(images.map(name => [`@images/${name}.svg?react`, svg(`${name}.svg?react`)])),
        "@images/brand/icon-small.svg": "brand", "../version_label/VersionLabel.jsx": { VersionLabel: "version" },
    });
    const tabs = all(runtime.render(sidebar.SidebarSection), node => typeof node.props?.tab_id === "string").map(node => node.props.tab_id);
    assert.deepEqual(tabs.slice(tabs.indexOf("vrchat"), tabs.indexOf("vrchat") + 3), ["vrchat", "ocr", "vr"]);
    const shown = id => sidebar.TabIcon({ tab_id: id, className: "" });
    assert.ok(shown("ocr"));
    assert.notEqual(shown("ocr").type, shown("vrchat").type);
    for (const language of ["en", "ja"]) {
        const strings = yaml.load(readFileSync(new URL(`../../../../locales/${language}.yml`, import.meta.url), "utf8"));
        assert.equal(typeof strings.config_page.side_menu_labels.ocr, "string");
        for (const key of ["provider_in_use", "provider_ready", "provider_not_set"]) assert.equal(typeof strings.config_page.translation[key], "string");
    }
});

test("speech recognition opens on the engine choice; the timing numbers follow", () => {
    const source = readFileSync(new URL("./setting_section/setting_box/transcription/Transcription.jsx", import.meta.url), "utf8");
    const page = source.split("export const Transcription = () => {")[1].split("\n};")[0];
    const order = [...page.matchAll(/<([A-Z][A-Za-z_]+)/g)].map(match => match[1]);
    assert.deepEqual(order, ["TranscriptionEngine_Container", "CloudTranscription_Container", "Mic_Container", "Speaker_Container",
        "RealtimeASRSettings", "SpeechServers"]);
});

test("each translation provider is one fold that says whether it can be used; the one in use stays open", async () => {
    const runtime = hooks();
    const engines = [{ id: "DeepL_API", label: "DeepL API", is_available: true }, { id: "Gemini_API", label: "Gemini API", is_available: false },
        { id: "Ollama", label: "Ollama", is_available: true }];
    let selected = { 1: "CTranslate2", 2: "Ollama", 3: "CTranslate2" };
    const SetupSection = () => null;
    const source = readFileSync(new URL("./setting_section/setting_box/translation/Translation.jsx", import.meta.url), "utf8");
    const dependencies = Object.fromEntries([...source.matchAll(/from "([^"]+)"/g)].map(match => [match[1], {}]));
    const translation = await loadModule(new URL("./setting_section/setting_box/translation/Translation.jsx", import.meta.url), runtime, {
        ...dependencies, react: runtime.api,
        "@useI18n": { useI18n: () => ({ t: key => key }) },
        "@store": { useStore_TranslationEngines: () => ({ currentTranslationEngines: { data: engines } }),
            useStore_SelectedTranslationEngines: () => ({ currentSelectedTranslationEngines: { data: selected } }) },
        "../_components/setup_section/SetupSection": { SetupSection },
    });
    // Translation's own sections are not exported; draw them through the page.
    const page = runtime.render(translation.Translation);
    const folds = [];
    for (const section of page.props.children.slice(1)) {
        const drawn = section.type(section.props);
        for (const provider of all(drawn, node => typeof node.props?.id === "string" && typeof node.type === "function")) {
            const fold = provider.type(provider.props);
            assert.equal(fold.type, SetupSection);
            folds.push([provider.props.id, fold.props.title, fold.props.status, fold.props.attention]);
        }
    }
    assert.deepEqual(folds.map(fold => fold[0]), ["DeepL_API", "Plamo_API", "Gemini_API", "OpenAI_API", "Groq_API", "OpenRouter_API",
        "LMStudio", "Ollama", "OpenAI_Compatible"]);
    const by = Object.fromEntries(folds.map(([id, ...rest]) => [id, rest]));
    assert.deepEqual(by.DeepL_API, ["DeepL API", "config_page.translation.provider_ready", false]);
    assert.deepEqual(by.Gemini_API, ["Gemini API", "config_page.translation.provider_not_set", false]);
    assert.deepEqual(by.Ollama, ["Ollama", "config_page.translation.provider_in_use", true]);
    assert.deepEqual(by.Plamo_API, ["Plamo_API", "config_page.translation.provider_not_set", false], "an engine the list does not know keeps its id");
});
