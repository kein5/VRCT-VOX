import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";

import { useLanguageSettings } from "@logics_main";
import styles from "./LanguageSelector.module.scss";

import { LanguageSelectorTopBar } from "./language_selector_top_bar/LanguageSelectorTopBar";
export const LanguageSelector = ({ title, onClickFunction }) => {
    const { t } = useI18n();
    const { currentSelectableLanguageList } = useLanguageSettings();

    const groupLanguagesByFirstLetter = (languages) => {
        return languages.reduce((acc, { language, country }) => {
            const firstLetter = language[0].toUpperCase();
            if (!acc[firstLetter]) {
                acc[firstLetter] = [];
            }
            acc[firstLetter].push({ language, country });
            return acc;
        }, {});
    };

    // Typing narrows the list by language or country; Enter picks the first
    // match. The field takes focus when the selector opens.
    const [query, setQuery] = useState("");
    const filter = useRef(null);
    useEffect(() => { filter.current?.focus({ preventScroll: true }); }, []);
    const needle = query.trim().toLowerCase();
    const shown = needle
        ? currentSelectableLanguageList.data.filter(({ language, country }) => `${language} ${country}`.toLowerCase().includes(needle))
        : currentSelectableLanguageList.data;
    const groupedLanguages = groupLanguagesByFirstLetter(shown);

    return (
        <div className={styles.container}>
            <LanguageSelectorTopBar title={title}/>
            <div className={styles.language_list_scroll_wrapper}>
                <div className={styles.filter_row}>
                    <input ref={filter} type="search" className={styles.filter} value={query}
                        placeholder={t("main_page.language_selector.filter")} aria-label={t("main_page.language_selector.filter")}
                        onChange={event => setQuery(event.target.value)}
                        onKeyDown={event => {
                            if (event.key === "Enter" && shown.length) {
                                event.preventDefault();
                                onClickFunction({ language: shown[0].language, country: shown[0].country });
                            }
                        }} />
                </div>
                {shown.length ? (
                    <div className={styles.language_list}>
                        {Object.entries(groupedLanguages).map(([letter, languages]) => (
                            <LanguageGroup key={letter} onClickFunction={onClickFunction} letter={letter} languages={languages} />
                        ))}
                    </div>
                ) : (
                    <p role="status" className={styles.no_results}>{t("main_page.language_selector.no_results")}</p>
                )}
            </div>
        </div>
    );
};

const LanguageGroup = ({ onClickFunction, letter, languages }) => {
    return (
        <div className={styles.language_each_letter_box}>
            <p className={styles.language_latter}>{letter}</p>
            {languages.map((language_data, index) => (
                <LanguageButton key={index} onClickFunction={onClickFunction} language_data={language_data} />
            ))}
        </div>
    );
};

const LanguageButton = ({ onClickFunction, language_data }) => {

    const adjustedOnClickFunction = () => {
        onClickFunction({
            language: language_data.language,
            country: language_data.country,
        });
    };

    return (
        <button type="button" className={styles.language_button} onClick={adjustedOnClickFunction}>
            <span className={styles.language_label}>{language_data.language} ({language_data.country})</span>
        </button>
    );
};