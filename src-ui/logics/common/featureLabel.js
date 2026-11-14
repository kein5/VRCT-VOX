// A feature's name says what it does, then its short name in brackets: 「テキスト読み上げ（TTS）」,
// "Text to speech (TTS)". Where the name does not fit on one line, it breaks before the bracket
// instead of anywhere, so the short name sits whole on the line below.
const PATTERN = /^(.*\S)\s*([（(][^（）()]+[）)])$/u;

export const splitFeatureLabel = label => {
    const match = PATTERN.exec(label ?? "");
    if (!match || /[（）()]/u.test(match[1])) return { name: label ?? "", abbr: null };
    return { name: match[1], abbr: match[2] };
};
