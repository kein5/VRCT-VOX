import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import styles from "./LanguageSelectorTopBar.module.scss";
import { useStore_IsOpenedLanguageSelector } from "@store";

export const LanguageSelectorTopBar = (props) => {
    const { t } = useI18n();
    const { updateIsOpenedLanguageSelector } = useStore_IsOpenedLanguageSelector();
    // Keyboard users land in the selector when it opens.
    const back = useRef(null);
    useEffect(() => { back.current?.focus({ preventScroll: true }); }, []);
    const closeLanguageSelector = () => {
        updateIsOpenedLanguageSelector({
            your_language: false,
            target_language: false,
            target_key: "1"
        });
    };

    return (
        <div className={styles.container}>
            <button type="button" ref={back} className={styles.go_back_button_wrapper} onClick={closeLanguageSelector}>
                <span className={styles.go_back_button_label}>{t("common.go_back_button_label")}</span>
            </button>
            <p className={styles.title}>{props.title}</p>
        </div>
    );
};