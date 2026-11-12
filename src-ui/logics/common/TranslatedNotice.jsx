import { useI18n } from "@useI18n";

// A notice whose text is chosen when it is drawn, not when it is raised.
// Notices raised during startup arrive before the saved UI language is applied;
// text fixed at that moment stayed English whatever the language. Drawn through
// the i18n hook, the notice also follows a language change while it is up.
// `labels` are other locale keys filled into the message, such as the name of a switch.
export const TranslatedNotice = ({ k, labels = {}, values = {} }) => {
    const { t } = useI18n();
    const names = Object.fromEntries(Object.entries(labels).map(([name, key]) => [name, t(key)]));
    return t(k, { ...values, ...names });
};
