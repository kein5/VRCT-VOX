import clsx from "clsx";
import { useI18n } from "@useI18n";
import styles from "./AddRemoveTargetLanguageButtons.module.scss";
import RemoveSvg from "@images/remove.svg?react";
import AddSvg from "@images/add.svg?react";

import { useLanguageSettings } from "@logics_main";

export const AddRemoveTargetLanguageButtons = () => {
    const { t } = useI18n();
    const {
        currentSelectedPresetTabNumber,
        // currentSelectedYourLanguages,
        currentSelectedTargetLanguages,
        canChangeLanguageSettings,
        isLanguageSettingsBusy,
        removeTargetLanguage,
        addTargetLanguage,
    } = useLanguageSettings();

    const remove_button_class = clsx(styles.remove_target_language_button, {
        [styles.is_disabled]: !currentSelectedTargetLanguages.data[currentSelectedPresetTabNumber.data]["2"].enable,
    });
    const add_button_class = clsx(styles.add_target_language_button, {
        [styles.is_disabled]: currentSelectedTargetLanguages.data[currentSelectedPresetTabNumber.data]["3"].enable,
    });

    return (
        <div className={styles.add_remove_target_language_container}>
            <div className={remove_button_class} aria-disabled={isLanguageSettingsBusy} onClick={() => { if (canChangeLanguageSettings()) removeTargetLanguage(); }}
                role="button" tabIndex={0} aria-label={t("main_page.remove_target_language")}
                onKeyDown={event => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); if (event.repeat) return; if (canChangeLanguageSettings()) removeTargetLanguage(); } }}>
                <RemoveSvg className={styles.remove_svg} aria-hidden="true" />
            </div>
            <div className={add_button_class} aria-disabled={isLanguageSettingsBusy} onClick={() => { if (canChangeLanguageSettings()) addTargetLanguage(); }}
                role="button" tabIndex={0} aria-label={t("main_page.add_target_language")}
                onKeyDown={event => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); if (event.repeat) return; if (canChangeLanguageSettings()) addTargetLanguage(); } }}>
                <AddSvg className={styles.add_svg} aria-hidden="true" />
            </div>
        </div>
    );
};