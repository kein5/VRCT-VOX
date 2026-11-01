// Japanese ends a sentence with "。", English with ". "; the first one stays visible.
const SENTENCE_END = /(。|[.!?](?=\s))/;
// Below this many characters the rest is short enough to show in full.
const FOLD_AFTER = 24;

// [visible, folded]: the first sentence, and the rest when it is long enough to fold.
export const splitDescription = text => {
    const value = text ?? "";
    const match = SENTENCE_END.exec(value);
    if (!match) return [value, ""];
    const end = match.index + match[0].length;
    const rest = value.slice(end).trim();
    return rest.length > FOLD_AFTER ? [value.slice(0, end), rest] : [value, ""];
};
