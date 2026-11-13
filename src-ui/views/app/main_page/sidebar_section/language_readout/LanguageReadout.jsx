import { useI18n } from "@useI18n";
import { createLanguageNames } from "../../../../../logics/common/languageNames.js";
import styles from "./LanguageReadout.module.scss";
import ArrowDownSvg from "@images/narrow_arrow_down.svg?react";
import { useIsMainPageCompactMode, useLanguageSettings } from "@logics_main";

// The icon rail hides the language controls. This keeps the selected pair in
// sight (your language, then the first language of the other side and how many
// more), and opens the rail to change it, as the top bar's toggle does.
export const LanguageReadout = () => {
    const { t, i18n } = useI18n();
    const { currentSelectedPresetTabNumber, currentSelectedYourLanguages, currentSelectedTargetLanguages } = useLanguageSettings();
    const { toggleIsMainPageCompactMode } = useIsMainPageCompactMode();
    const preset = currentSelectedPresetTabNumber.data;
    const yours = currentSelectedYourLanguages.data?.[preset]?.["1"];
    const targets = Object.values(currentSelectedTargetLanguages.data?.[preset] ?? {}).filter(entry => entry && entry.enable !== false);
    if (!yours || targets.length === 0) return null;
    const names = createLanguageNames(i18n.language);
    const from = names.name(yours).language, to = names.name(targets[0]).language;
    if (!from || !to) return null;
    const more = targets.length - 1;
    const pair = t("main_page.language_pair", { from, to: more > 0 ? `${to} +${more}` : to });
    return (
        <button type="button" className={styles.container} title={pair}
            aria-label={`${t("main_page.language_settings")}: ${pair}`} onClick={toggleIsMainPageCompactMode}>
            <span className={styles.name}>{from}</span>
            <ArrowDownSvg className={styles.arrow} aria-hidden="true" />
            <span className={styles.name}>{to}</span>
            {more > 0 && <span className={styles.more}>+{more}</span>}
        </button>
    );
};
