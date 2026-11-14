import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { hooks, loadModule, find } from "../../../logics/test/hookHarness.js";
import * as featureLabel from "../../../logics/common/featureLabel.js";

const all = (tree, predicate, found = []) => { find(tree, node => { if (predicate(node)) found.push(node); return false; }); return found; };
const icon = name => Object.assign(() => null, { icon: name });

test("chat reading has a page of its own, and search lists it there", async () => {
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
    assert.deepEqual(search.settingTabs("ocr", "source_language"), ["ocr"]);
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
        "../../../../logics/common/featureLabel.js": featureLabel,
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

test("a long settings menu name breaks before its bracket and keeps its whole name for screen readers", async () => {
    const runtime = hooks();
    const names = { "config_page.side_menu_labels.transcription": "Speech recognition (ASR)" };
    const svg = name => icon(name);
    const images = ["mic", "tts_speaker", "voice_conversion", "mui_palette", "translation", "mui_graphic_eq", "mui_head_mounted_device",
        "mui_keyboard_alt", "mui_code_blocks", "refresh", "chat_transcribe", "mui_document_scanner"];
    const sidebar = await loadModule(new URL("./sidebar_section/SidebarSection.jsx", import.meta.url), runtime, {
        "@useI18n": { useI18n: () => ({ t: key => names[key] ?? key }) },
        "@store": { useStore_SelectedConfigTabId: () => ({ currentSelectedConfigTabId: { data: "device" }, updateSelectedConfigTabId() {} }),
            useStore_IsBreakPoint: () => ({ currentIsBreakPoint: { data: false } }) },
        ...Object.fromEntries(images.map(name => [`@images/${name}.svg?react`, svg(`${name}.svg?react`)])),
        "@images/brand/icon-small.svg": "brand", "../version_label/VersionLabel.jsx": { VersionLabel: "version" },
        "../../../../logics/common/featureLabel.js": featureLabel,
    });
    const [tab] = all(runtime.render(sidebar.SidebarSection), node => node.props?.tab_id === "transcription");
    const tree = runtime.render(tab.type, tab.props);
    assert.ok(find(tree, node => node.props?.["aria-label"] === "Speech recognition (ASR)"));
    assert.ok(find(tree, node => node.type === "span" && node.props?.children === "(ASR)"));
    assert.ok(find(tree, node => Array.isArray(node.props?.children) && node.props.children[0] === "Speech recognition"));
});

test("speech recognition opens on the engine choice; the timing numbers follow, folded under a line that shows them", async () => {
    const source = readFileSync(new URL("./setting_section/setting_box/transcription/Transcription.jsx", import.meta.url), "utf8");
    const page = source.split("export const Transcription = () => {")[1].split("\n};")[0];
    const order = [...page.matchAll(/<([A-Z][A-Za-z_]+)/g)].map(match => match[1]);
    assert.deepEqual(order, ["TranscriptionEngine_Container", "CloudTranscription_Container", "Mic_Container", "Speaker_Container",
        "RealtimeASRSettings", "SpeechServers"]);
    const section = name => source.split(`const ${name} = () => {`)[1].split("\n};")[0];
    // The word filter is a list people edit; it stays in sight. The three numbers are folded.
    assert.match(section("Mic_Container"), /<MicWordFilter_Box \/>\s*<TimingFold silence=\{currentMicRecordTimeout\.data\} length=\{currentMicPhraseTimeout\.data\} queue=\{currentMicMaxWords\.data\}>\s*<MicRecordTimeout_Box \/>\s*<MicPhraseTimeout_Box \/>\s*<MicMaxWords_Box \/>\s*<\/TimingFold>/);
    assert.match(section("Speaker_Container"), /<TimingFold silence=\{currentSpeakerRecordTimeout\.data\} length=\{currentSpeakerPhraseTimeout\.data\} queue=\{currentSpeakerMaxWords\.data\}>\s*<SpeakerRecordTimeout_Box \/>\s*<SpeakerPhraseTimeout_Box \/>\s*<SpeakerMaxWords_Box \/>\s*<\/TimingFold>/);
    assert.match(section("TranscriptionEngine_Container"), /thresholds_title[\s\S]*<MicAvgLogprobContainer \/>\s*<MicNoSpeechProbContainer \/>\s*<SpeakerAvgLogprobContainer \/>\s*<SpeakerNoSpeechProbContainer \/>\s*<\/SetupSection>/);

    const runtime = hooks();
    const SetupSection = () => null;
    const dependencies = Object.fromEntries([...source.matchAll(/from "([^"]+)"/g)].map(match => [match[1], {}]));
    const t = (key, options) => options ? `${key}:${Object.values(options).join(",")}` : key;
    const transcription = await loadModule(new URL("./setting_section/setting_box/transcription/Transcription.jsx", import.meta.url), runtime, {
        ...dependencies, react: runtime.api, "@useI18n": { useI18n: () => ({ t }) },
        "@logics_configs": { useTranscription: () => ({ currentMicRecordTimeout: { data: 3 }, currentMicPhraseTimeout: { data: 5 }, currentMicMaxWords: { data: 10 } }) },
        "../_components/setup_section/SetupSection": { SetupSection },
    });
    const mic = runtime.render(transcription.Transcription).props.children.find(node => node?.type?.name === "Mic_Container");
    const fold = find(mic.type(mic.props), node => node.type?.name === "TimingFold");
    const drawn = fold.type(fold.props);
    assert.equal(drawn.type, SetupSection);
    assert.equal(drawn.props.title, "config_page.transcription.timing_title");
    assert.equal(drawn.props.status, "config_page.transcription.timing_status:3,5,10");
    assert.equal(drawn.props.attention, undefined, "closed until opened");
});

test("each cloud speech recognition provider is one fold; the selected one stays open", async () => {
    const runtime = hooks();
    const SetupSection = () => null;
    const source = readFileSync(new URL("./setting_section/setting_box/transcription/Transcription.jsx", import.meta.url), "utf8");
    const dependencies = Object.fromEntries([...source.matchAll(/from "([^"]+)"/g)].map(match => [match[1], {}]));
    const engines = [{ id: "Groq_Whisper", base: "GroqWhisper", key: "groq_whisper" }, { id: "Custom_Whisper", base: "CustomWhisper", key: "custom_whisper", has_url: true },
        { id: "Deepgram", base: "Deepgram", key: "deepgram" }];
    const state = { currentSelectedTranscriptionEngine: { data: "Deepgram" }, currentSelectableTranscriptionEngines: { data: ["Google", "Groq_Whisper", "Deepgram"] },
        currentCustomWhisperURL: { data: "" }, getSelectableTranscriptionEngines() {}, getSelectedTranscriptionEngine() {},
        ...Object.fromEntries(engines.map(engine => [`current${engine.base}AuthKey`, { data: null }])) };
    const transcription = await loadModule(new URL("./setting_section/setting_box/transcription/Transcription.jsx", import.meta.url), runtime, {
        ...dependencies, react: runtime.api, "@useI18n": { useI18n: () => ({ t: key => key }) },
        "@logics_configs": { useTranscription: () => state },
        "../../../../../../logics/configs/cloudTranscription": { CLOUD_TRANSCRIPTION_ENGINES: engines },
        "../_components/setup_section/SetupSection": { SetupSection },
    });
    const cloud = runtime.render(transcription.Transcription).props.children.find(node => node?.type?.name === "CloudTranscription_Container");
    const folds = all(runtime.render(cloud.type, cloud.props), node => node.type === SetupSection)
        .map(node => [node.props.title.split(".").at(-1), node.props.status.split(".").at(-1), node.props.attention]);
    assert.deepEqual(folds, [["groq_whisper", "provider_ready", false], ["custom_whisper", "provider_not_set", false], ["deepgram", "provider_in_use", true]]);
});

test("the VRChat page no longer carries chat reading; it ends with the way to that page", async () => {
    const runtime = hooks(), opened = [];
    const source = readFileSync(new URL("./setting_section/setting_box/vrchat/Vrchat.jsx", import.meta.url), "utf8");
    assert.doesNotMatch(source, /ocr\/Ocr/);
    const dependencies = Object.fromEntries([...source.matchAll(/from "([^"]+)"/g)].map(match => [match[1], {}]));
    const vrchat = await loadModule(new URL("./setting_section/setting_box/vrchat/Vrchat.jsx", import.meta.url), runtime, {
        ...dependencies, react: runtime.api, "@useI18n": { useI18n: () => ({ t: key => key }) },
        "@store": { useStore_SelectedConfigTabId: () => ({ updateSelectedConfigTabId: id => opened.push(id) }) },
    });
    const page = runtime.render(vrchat.Vrchat);
    const last = page.props.children.at(-1);
    const pointer = last.type(last.props);
    const button = find(pointer, node => node.type === "button");
    assert.equal(button.props.children, "config_page.vrchat.open_chat_reading");
    button.props.onClick();
    assert.deepEqual(opened, ["ocr"]);
    for (const language of ["en", "ja"]) {
        const strings = yaml.load(readFileSync(new URL(`../../../../locales/${language}.yml`, import.meta.url), "utf8")).config_page;
        for (const key of ["chat_reading_moved", "open_chat_reading"]) assert.equal(typeof strings.vrchat[key], "string");
        for (const key of ["timing_title", "timing_status", "thresholds_title", "thresholds_status"]) assert.equal(typeof strings.transcription[key], "string");
    }
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
