import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@useI18n";

import { useLanguageSettings } from "@logics_main";
import { createLanguageNames, isLanguagePickKey } from "../../../../../logics/common/languageNames.js";
import styles from "./LanguageSelector.module.scss";

import { LanguageSelectorTopBar } from "./language_selector_top_bar/LanguageSelectorTopBar";
export const LanguageSelector = ({ title, onClickFunction }) => {
    const { t, i18n } = useI18n();
    const names = useMemo(() => createLanguageNames(i18n.language), [i18n.language]);
    const { currentSelectableLanguageList } = useLanguageSettings();

    // Typing narrows the list by language or country; Enter picks the first
    // match. The field takes focus when the selector opens.
    const [query, setQuery] = useState("");
    const filter = useRef(null);
    useEffect(() => { filter.current?.focus({ preventScroll: true }); }, []);
    const shown = useMemo(() => names.sorted(currentSelectableLanguageList.data ?? [])
        .filter(entry => names.matches(entry, query)), [names, currentSelectableLanguageList.data, query]);

    return (
        <div className={styles.container}>
            <LanguageSelectorTopBar title={title}/>
            <div className={styles.language_list_scroll_wrapper}>
                <div className={styles.filter_row}>
                    <input ref={filter} type="search" className={styles.filter} value={query}
                        placeholder={t("main_page.language_selector.filter")} aria-label={t("main_page.language_selector.filter")}
                        onChange={event => setQuery(event.target.value)}
                        onKeyDown={event => {
                            if (isLanguagePickKey(event) && shown.length) {
                                event.preventDefault();
                                onClickFunction({ language: shown[0].language, country: shown[0].country });
                            }
                        }} />
                </div>
                {shown.length ? (
                    <div className={styles.language_list}>
                        {shown.map(entry => (
                            <LanguageButton key={`${entry.language}/${entry.country}`} onClickFunction={onClickFunction}
                                language_data={entry} label={names.name(entry).label} />
                        ))}
                    </div>
                ) : (
                    <p role="status" className={styles.no_results}>{t("main_page.language_selector.no_results")}</p>
                )}
            </div>
        </div>
    );
};

const LanguageButton = ({ onClickFunction, language_data, label }) => {

    const adjustedOnClickFunction = () => {
        onClickFunction({
            language: language_data.language,
            country: language_data.country,
        });
    };

    return (
        <button type="button" className={styles.language_button} onClick={adjustedOnClickFunction}>
            <span className={styles.language_label}>{label}</span>
        </button>
    );
};
