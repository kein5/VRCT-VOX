import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import i18next from "i18next";
import yaml from "js-yaml";

// The name of each feature, the same in the app and on the site: what it does, then its short name.
const LANGUAGES = ["ja", "en"];
const sources = Object.fromEntries(LANGUAGES.map(language => [language,
    readFileSync(new URL(`../../../locales/${language}.yml`, import.meta.url), "utf8")]));
const resources = Object.fromEntries(LANGUAGES.map(language => [language, { translation: yaml.load(sources[language]) }]));

const NAMES = {
    ja: {
        "main_page.tts": "テキスト読み上げ（TTS）", "main_page.rvc": "ボイスチェンジャー（RVC）",
        "main_page.ocr": "チャット読み取り（OCR）", "main_page.transcription_send": "マイク入力",
        "main_page.transcription_receive": "聞き取り",
        "config_page.side_menu_labels.tts": "テキスト読み上げ（TTS）", "config_page.side_menu_labels.rvc": "ボイスチェンジャー（RVC）",
        "config_page.side_menu_labels.transcription": "音声認識（ASR）", "config_page.side_menu_labels.ocr": "チャット読み取り（OCR）",
        "config_page.tts.tts_settings.label": "テキスト読み上げ（TTS）", "config_page.rvc.rvc_settings.label": "ボイスチェンジャー（RVC）",
    },
    en: {
        "main_page.tts": "Text to speech (TTS)", "main_page.rvc": "Voice changer (RVC)",
        "main_page.ocr": "Chat reading (OCR)", "main_page.transcription_send": "Mic input",
        "main_page.transcription_receive": "Listening",
        "config_page.side_menu_labels.tts": "Text to speech (TTS)", "config_page.side_menu_labels.rvc": "Voice changer (RVC)",
        "config_page.side_menu_labels.transcription": "Speech recognition (ASR)", "config_page.side_menu_labels.ocr": "Chat reading (OCR)",
        "config_page.tts.tts_settings.label": "Text to speech (TTS)", "config_page.rvc.rvc_settings.label": "Voice changer (RVC)",
    },
};

// Old ways of pointing the user at a page or a switch. None may be left in the text (comments aside).
const STALE = {
    ja: ["設定の「TTS」", "「TTS」で", "TTSの設定", "TTS設定", "でTTSをオン", "TTSをオンに", "RVCスイッチ", "RVC設定",
        "設定 → 音声認識 →", "設定の「音声認識」", "「チャット読み取り」で", "「チャット読み取り」の設定",
        "「チャット読み取り」のページ", "チャット読み取りをオン", "音声認識の設定", "または「音声認識」"],
    en: ["Chat Transcribe", "Voice2Chatbox", "Speaker2Log", "Settings → Transcription", "Settings → TTS",
        "TTS settings", "the TTS page", "turn on TTS", "turn TTS on", "Turn on TTS", "Turn TTS on",
        "the RVC page", "RVC switch", "Transcription settings"],
};

for (const language of LANGUAGES) {
    test(`${language}: features carry the same names everywhere`, async () => {
        const i18n = i18next.createInstance();
        await i18n.init({ lng: language, fallbackLng: false, resources });
        for (const [key, name] of Object.entries(NAMES[language])) assert.equal(i18n.t(key), name, key);
    });

    test(`${language}: no text points at a page or switch by its old name`, () => {
        const found = [];
        sources[language].split("\n").forEach((line, index) => {
            if (/^\s*#/.test(line)) return;
            for (const stale of STALE[language]) if (line.includes(stale)) found.push(`${index + 1}: ${stale}`);
        });
        assert.deepEqual(found, []);
    });
}
