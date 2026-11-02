import test from "node:test";
import assert from "node:assert/strict";
import { createLanguageNames, isLanguagePickKey } from "./languageNames.js";
import { languageCodes } from "./languageCodes.js";

const japanese = Object.freeze({ language: "Japanese", country: "Japan" });
const english = Object.freeze({ language: "English", country: "United States" });
const locales = ["en", "ja", "ko", "zh-Hant", "zh-Hans"];

for (const locale of locales) {
    test(`${locale}: names use the current UI language and preserve the original identity`, () => {
        const names = createLanguageNames(locale);
        const language = new Intl.DisplayNames(locale, { type: "language" }).of("ja");
        const country = new Intl.DisplayNames(locale, { type: "region" }).of("JP");
        assert.deepEqual(names.name(japanese), { language, country, label: `${language} (${country})` });
        for (const query of [language, country, "Japanese", "japan", "jApAnEsE JAPAN"]) {
            assert.equal(names.matches(japanese, query), true, query);
        }
        assert.deepEqual(japanese, { language: "Japanese", country: "Japan" });
    });
}

test("Japanese search accepts either language, mixed tokens, case and width, and rejects unrelated entries", () => {
    const names = createLanguageNames("ja");
    assert.equal(names.name(japanese).label, "日本語 (日本)");
    for (const query of ["日本語", "日本", "Japanese", "japan", "日本語 japan", "ＪＡＰＡＮ", "  "]) {
        assert.equal(names.matches(japanese, query), true, query);
    }
    assert.equal(names.matches(japanese, "Korean"), false);
    assert.equal(names.matches(japanese, "日本語 Korea"), false);
    assert.equal(names.matches(english, "日本"), false);
});

test("sorting and filtering return original objects in visible order for Enter selection", () => {
    const entries = Object.freeze([japanese, english, Object.freeze({ language: "Arabic", country: "Algeria" })]);
    const names = createLanguageNames("ja");
    const sorted = names.sorted(entries);
    const expected = [...entries].sort((a, b) => new Intl.Collator("ja").compare(names.name(a).label, names.name(b).label));
    assert.deepEqual(sorted, expected);
    assert.strictEqual(sorted.filter(entry => names.matches(entry, "japan"))[0], japanese);
    assert.deepEqual(entries, [japanese, english, { language: "Arabic", country: "Algeria" }]);
});

test("all source tags are valid and localized in each supported UI locale", () => {
    let count = 0;
    for (const [language, countries] of Object.entries(languageCodes)) {
        for (const [country, code] of Object.entries(countries)) {
            const tag = new Intl.Locale(code);
            assert.ok(tag.region);
            for (const locale of locales) {
                const names = createLanguageNames(locale);
                const display = names.name({ language, country });
                assert.ok(display.language);
                assert.ok(display.country);
                assert.ok(names.matches({ language, country }, display.label));
            }
            count++;
        }
    }
    assert.ok(count > 0);
});

test("scripts, Cantonese, legacy Hebrew tags and lowercase country identities are handled", () => {
    const names = createLanguageNames("ja");
    const simplified = names.name({ language: "Chinese Simplified", country: "China" });
    const traditional = names.name({ language: "Chinese Traditional", country: "Taiwan" });
    assert.notEqual(simplified.language, traditional.language);
    assert.match(simplified.language, /簡体/);
    assert.match(traditional.language, /繁体/);
    assert.match(names.name({ language: "Chinese Traditional", country: "Hong Kong" }).language, /広東/);
    assert.match(names.name({ language: "Hebrew", country: "Israel" }).language, /ヘブライ/);
    assert.equal(names.name({ language: "Tamil", country: "malaysia" }).country, "マレーシア");
});

test("missing or invalid tags and absent Intl preserve English names", () => {
    const names = createLanguageNames("ja");
    const unknown = { language: "Future language", country: "Future region" };
    assert.equal(names.name(unknown).label, "Future language (Future region)");
    assert.equal(names.name({ ...japanese, code: "invalid_tag" }).label, "Japanese (Japan)");
    assert.equal(createLanguageNames("ja", {}).name(japanese).label, "Japanese (Japan)");
    assert.equal(createLanguageNames("ja", {}).fromCode("ja"), "ja");
    assert.equal(createLanguageNames("bad_locale").name(japanese).label, "Japanese (Japan)");
    assert.equal(names.name(null).label, "");
    assert.deepEqual(createLanguageNames("ja", {}).sorted([japanese, english]), [japanese, english]);
});

test("DisplayNames returning nothing or throwing falls back independently for each part", () => {
    for (const failType of ["language", "region"]) {
        for (const failure of [undefined, "", "throw"]) {
            const platform = { Locale: Intl.Locale, Collator: Intl.Collator, DisplayNames: class {
                constructor(locale, options) { this.type = options.type; this.real = new Intl.DisplayNames(locale, options); }
                of(code) {
                    if (this.type !== failType) return this.real.of(code);
                    if (failure === "throw") throw new RangeError();
                    return failure;
                }
            } };
            const names = createLanguageNames("ja", platform);
            assert.equal(names.name(japanese).label, failType === "language" ? "Japanese (日本)" : "日本語 (Japan)");
            assert.ok(names.matches(japanese, "Japanese Japan"));
        }
    }
});

test("unknown valid codes fall back to English instead of showing raw tags", () => {
    assert.equal(createLanguageNames("ja").name({ ...japanese, code: "qzz-QZ" }).label, "Japanese (Japan)");
});

test("language-only OCR, realtime codes and UI options use localized labels without changing IDs", () => {
    const names = createLanguageNames("ja");
    assert.equal(names.language("Korean"), "韓国語");
    assert.equal(names.name({ language: "Korean" }).label, "韓国語");
    assert.equal(names.matches({ language: "Korean" }, "韓国語"), true);
    assert.equal(names.language("Unknown"), "Unknown");
    assert.equal(names.language("Japanese"), "日本語"); // legacy OCR value
    assert.equal(names.fromCode("ja"), "日本語");
    assert.equal(names.fromCode("en-US"), "英語 (アメリカ合衆国)");
    assert.equal(names.fromCode("not_a_code"), "not_a_code");
    const options = Object.freeze([Object.freeze({ id: "ko", label: "한국어" })]);
    assert.deepEqual(names.uiOptions(options), [{ id: "ko", label: "韓国語 / 한국어" }]);
    assert.equal(createLanguageNames("ko").uiOptions(options)[0].label, "한국어");
});

test("changing UI language updates labels and search, including script-specific UI locales", () => {
    assert.notEqual(createLanguageNames("en").name(japanese).label, createLanguageNames("ja").name(japanese).label);
    assert.equal(createLanguageNames("ja").matches(japanese, "日本語"), true);
    assert.equal(createLanguageNames("en").matches(japanese, "日本語"), false);
    assert.notEqual(createLanguageNames("zh-Hans").fromCode("ko"), createLanguageNames("zh-Hant").fromCode("ko"));
});

test("Enter selects only after IME composition has ended", () => {
    assert.equal(isLanguagePickKey({ key: "Enter" }), true);
    assert.equal(isLanguagePickKey({ key: "Enter", nativeEvent: { isComposing: true } }), false);
    assert.equal(isLanguagePickKey({ key: "Enter", isComposing: true }), false);
    assert.equal(isLanguagePickKey({ key: "Enter", keyCode: 229 }), false);
    assert.equal(isLanguagePickKey({ key: "Escape" }), false);
});
