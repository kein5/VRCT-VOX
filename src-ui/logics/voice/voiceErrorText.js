// The main screen's notice for a voice code: its sentence with the code kept for support, from
// voice_ui.errors or, failing that, voice.input_errors (the voice pages' list). A code with no
// sentence, or text that is not a code, is shown as it is with the page to check.
export const voiceErrorText = (code, page, t, exists) => {
    if (/^[a-z0-9_]+$/.test(code)) {
        for (const key of [`voice_ui.errors.${code}`, `voice.input_errors.${code}`]) {
            if (exists(key)) return `${t(key)} (${code})`;
        }
    }
    return `${code} · ${t("voice_ui.check_settings", { page })}`;
};
