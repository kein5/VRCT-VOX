import test from "node:test";
import assert from "node:assert/strict";
import { languageJumpGroups } from "./languageJumpGroups.js";
import { createLanguageNames } from "./languageNames.js";
import { languageCodes } from "./languageCodes.js";

const group = (name, locale = "ja") => languageJumpGroups([name], locale)[0]?.id;

test("Japanese katakana names use kana rows, with kanji and other scripts separate", () => {
    const names = Object.freeze(["アラビア語", "カタルーニャ語", "スペイン語", "タイ語", "ネパール語",
        "フランス語", "マレー語", "ヨルバ語", "ロシア語", "ワロン語", "日本語", "中国語", "English"]);
    assert.deepEqual(languageJumpGroups(names, "ja-JP"), [
        ...[..."アカサタナハマヤラワ"].map((id, index) => ({ id, index })),
        { id: "other", index: 10 },
    ]);
    for (const name of ["日本語", "中国語", "英語", "韓国語", "English", "123", "", "   ", null]) {
        assert.equal(group(name), "other", String(name));
    }
});

test("Japanese voicing, small kana, hiragana and half-width names share their base row", () => {
    for (const [name, expected] of [
        ["ガンダ語", "カ"], ["ギリシャ語", "カ"], ["ジャワ語", "サ"], ["ヅ", "タ"],
        ["ベンガル語", "ハ"], ["ポーランド語", "ハ"], ["ヴェンダ語", "ア"],
        ["ぁ", "ア"], ["ィ", "ア"], ["ゥ", "ア"], ["ェ", "ア"], ["ォ", "ア"],
        ["ヵ", "カ"], ["ヶ", "カ"], ["ッ", "タ"], ["ャ", "ヤ"], ["ュ", "ヤ"], ["ョ", "ヤ"], ["ヮ", "ワ"],
        ["ぎりしゃ語", "カ"], ["ﾊﾟ", "ハ"], ["ｶﾞ", "カ"], ["カ\u3099ンダ語", "カ"],
        ["ン", "ワ"], ["ヲ", "ワ"],
    ]) assert.equal(group(name), expected, name);
});

test("Japanese prolonged-sound marks do not become a jump group", () => {
    assert.equal(group("ラオ語"), "ラ");
    assert.equal(group("ズールー語"), "サ");
    assert.equal(group("  ーーガンダ語"), "カ");
    assert.equal(group("ｰｶﾞ"), "カ");
    assert.equal(group("ー"), "other");
});

test("English exposes only present A–Z initials and uses displayed names", () => {
    assert.deepEqual(languageJumpGroups(["Zulu", "arabic", "English", "English", "Éwé", " 日本語"], "en-US"), [
        { id: "A", index: 1 }, { id: "E", index: 2 }, { id: "Z", index: 0 }, { id: "other", index: 5 },
    ]);
    assert.equal(group("Ｆｒｅｎｃｈ", "en"), "F");
    assert.equal(group("  english", "EN"), "E");
});

test("Korean groups syllables by Hangul initial consonant, including doubled initials", () => {
    assert.deepEqual(languageJumpGroups(["한국어", "독일어", "러시아어", "영어", "일본어", "중국어", "日本語"], "ko-KR"), [
        { id: "ㄷ", index: 1 }, { id: "ㄹ", index: 2 }, { id: "ㅇ", index: 3 },
        { id: "ㅈ", index: 5 }, { id: "ㅎ", index: 0 }, { id: "other", index: 6 },
    ]);
    for (const [name, expected] of [["가", "ㄱ"], ["까", "ㄲ"], ["따", "ㄸ"], ["빠", "ㅃ"], ["싸", "ㅆ"], ["짜", "ㅉ"],
        ["ㄱ", "ㄱ"], ["ㄲ", "ㄲ"], ["한", "ㅎ"], ["힣", "ㅎ"], ["English", "other"], ["", "other"]]) {
        assert.equal(group(name, "ko"), expected, name);
    }
});

test("Chinese and unsupported locales have no guessed jump index", () => {
    for (const locale of ["zh-Hant", "zh-Hans", "zh-TW", "zh-CN", "fr", "ar", "bad_locale", "", undefined]) {
        assert.deepEqual(languageJumpGroups(["阿拉伯文", "中文", "日本語", "English"], locale), [], String(locale));
    }
    for (const locale of ["ja", "en", "ko"]) assert.deepEqual(languageJumpGroups([], locale), []);
});

test("filtering recomputes first indexes and removes absent groups without reordering input", () => {
    const names = Object.freeze(["English (UK)", "English (US)", "French", "Zulu"]);
    assert.deepEqual(languageJumpGroups(names, "en"), [
        { id: "E", index: 0 }, { id: "F", index: 2 }, { id: "Z", index: 3 },
    ]);
    assert.deepEqual(languageJumpGroups(names.filter(name => name !== "English (UK)" && name !== "French"), "en"), [
        { id: "E", index: 0 }, { id: "Z", index: 1 },
    ]);
    assert.deepEqual(names, ["English (UK)", "English (US)", "French", "Zulu"]);
});

test("real localized names drive jumps while sorted choices retain English selection identities", () => {
    const entries = Object.freeze(Object.entries(languageCodes).flatMap(([language, countries]) =>
        Object.keys(countries).map(country => Object.freeze({ language, country }))));
    for (const locale of ["ja", "en", "ko"]) {
        const names = createLanguageNames(locale);
        const choices = Object.freeze(names.sorted(entries));
        const labels = Object.freeze(choices.map(entry => names.name(entry).language));
        const groups = languageJumpGroups(labels, locale);
        assert.ok(groups.length > 1);
        for (const { id, index } of groups) {
            assert.equal(index, labels.findIndex(label => group(label, locale) === id));
            assert.strictEqual(choices[index], entries.find(entry => entry === choices[index]));
        }
        const japanese = choices.find(entry => entry.language === "Japanese");
        assert.equal(group(names.name(japanese).language, locale), { ja: "other", en: "J", ko: "ㅇ" }[locale]);
        assert.deepEqual(japanese, { language: "Japanese", country: "Japan" });
    }
});
