import { languageCodes } from "./languageCodes.js";

// Display metadata only. Always pass the original entry to selection callbacks.
export function createLanguageNames(uiLanguage, intl = globalThis.Intl) {
    const displayNames = type => {
        try { return new intl.DisplayNames([uiLanguage || "en"], { type, fallback: "none" }); }
        catch { return null; }
    };
    const languages = displayNames("language");
    const regions = displayNames("region");
    let collator;
    try { collator = new intl.Collator(uiLanguage || "en", { sensitivity: "base" }); }
    catch { /* Keep the supplied order when collation is unavailable. */ }
    const display = (names, code, fallback) => {
        if (!code) return fallback;
        try { return names?.of(code) || fallback; }
        catch { return fallback; }
    };
    const parsedTags = new Map();
    const parts = code => {
        if (parsedTags.has(code)) return parsedTags.get(code);
        try {
            const tag = new intl.Locale(code);
            // Retain the script to distinguish simplified/traditional Chinese.
            const result = { language: [tag.language, tag.script].filter(Boolean).join("-"), region: tag.region };
            parsedTags.set(code, result);
            return result;
        } catch { return {}; }
    };
    const codeFor = entry => entry?.code || (entry?.country ? languageCodes[entry.language]?.[entry.country]
        : Object.values(languageCodes[entry?.language] ?? {})[0]);
    const name = entry => {
        const tag = parts(codeFor(entry));
        const language = display(languages, tag.language, entry?.language ?? "");
        const country = entry?.country ? display(regions, tag.region, entry.country) : "";
        return { language, country, label: country ? `${language} (${country})` : language };
    };
    const normalize = value => String(value ?? "").normalize("NFKC").toLowerCase().trim();
    const searchText = entry => {
        const localized = name(entry);
        return normalize([localized.label, localized.language, localized.country,
            entry?.language, entry?.country, `${entry?.language ?? ""} (${entry?.country ?? ""})`].join(" "));
    };
    const matches = (entry, query) => {
        const text = searchText(entry);
        return normalize(query).split(/\s+/).every(word => text.includes(word));
    };
    const sorted = entries => [...entries].sort((a, b) => collator?.compare(name(a).label, name(b).label) ?? 0);
    // Settings with a language-only English identity (OCR), including legacy selections.
    const language = english => {
        const code = Object.values(languageCodes[english] ?? {})[0];
        return display(languages, parts(code).language, english ?? "");
    };
    // Realtime ASR and UI-language settings already use BCP-47 codes as IDs.
    const fromCode = (code, fallback) => {
        const tag = parts(code);
        const english = tag.language && Object.keys(languageCodes).find(key =>
            Object.values(languageCodes[key]).some(value => parts(value).language === tag.language));
        fallback ??= english || code;
        const label = display(languages, tag.language, fallback);
        const region = display(regions, tag.region, "");
        return region ? `${label} (${region})` : label;
    };
    const uiOptions = options => options.map(option => {
        const label = fromCode(option.id, option.label);
        // Keep autonyms so users can recover from choosing an unfamiliar UI language.
        return { ...option, label: label === option.label ? label : `${label} / ${option.label}` };
    });
    return { name, matches, searchText, sorted, language, fromCode, uiOptions };
}

// Enter while an IME is committing Japanese text must not select a language.
export const isLanguagePickKey = event => event.key === "Enter"
    && !event.nativeEvent?.isComposing && !event.isComposing && event.keyCode !== 229;
