const KANA_ROWS = [
    ["ア", "アイウエオァィゥェォ"],
    ["カ", "カキクケコヵヶ"],
    ["サ", "サシスセソ"],
    ["タ", "タチツテトッ"],
    ["ナ", "ナニヌネノ"],
    ["ハ", "ハヒフヘホ"],
    ["マ", "マミムメモ"],
    ["ヤ", "ヤユヨャュョ"],
    ["ラ", "ラリルレロ"],
    ["ワ", "ワヰヱヲンヮ"],
];
const LATIN_LETTERS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
const HANGUL_INITIALS = [..."ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"];

// Input is the displayed language names in their current (sorted/filtered) order.
// Return only present groups and the index of their first visible entry. Never
// reorder the list or derive selection identities from these display labels.
// "other" is a locale key sentinel; the view supplies its translated label.
export function languageJumpGroups(displayNames, uiLanguage) {
    const locale = String(uiLanguage ?? "").toLowerCase().split("-")[0];
    let order;
    let groupFor;
    if (locale === "ja") {
        order = KANA_ROWS.map(([row]) => row);
        groupFor = name => {
            // NFKD folds half-width kana and removes voicing. Ignore leading
            // prolonged-sound marks; a mark alone has no readable initial.
            let first = name.normalize("NFKD").replace(/[\u3099\u309a]/g, "").replace(/^ー+/, "")[0] ?? "";
            const code = first.charCodeAt(0);
            if (code >= 0x3041 && code <= 0x3096) first = String.fromCharCode(code + 0x60);
            return KANA_ROWS.find(([, kana]) => first && kana.includes(first))?.[0];
        };
    } else if (locale === "en") {
        order = LATIN_LETTERS;
        groupFor = name => {
            const first = name.normalize("NFKD").replace(/\p{M}/gu, "").toUpperCase()[0];
            return LATIN_LETTERS.includes(first) ? first : undefined;
        };
    } else if (locale === "ko") {
        order = HANGUL_INITIALS;
        groupFor = name => {
            // Modern syllables and compatibility jamo both decompose to a
            // leading jamo in U+1100..U+1112, including doubled consonants.
            const initial = name.normalize("NFKD").codePointAt(0) - 0x1100;
            return HANGUL_INITIALS[initial];
        };
    } else {
        // Chinese collation varies by locale/runtime; no guessed pronunciation
        // or stroke index. Unsupported UI locales keep scrolling and filtering.
        return [];
    }
    const firstIndexes = new Map();
    displayNames.forEach((name, index) => {
        const id = groupFor(String(name ?? "").trim()) ?? "other";
        if (!firstIndexes.has(id)) firstIndexes.set(id, index);
    });
    return [...order, "other"].filter(id => firstIndexes.has(id))
        .map(id => ({ id, index: firstIndexes.get(id) }));
}
