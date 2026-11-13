import { useI18n } from "@useI18n";
import styles from "./WordFilter.module.scss";
import { _Entry } from "../_atoms/_entry/_Entry";
import { useState, useRef, useEffect, useCallback } from "react";
import { useStore_IsOpenedMicWordFilterList } from "@store";
import { useTranscription } from "@logics_configs";
import { useSettingsDraft } from "../../../../../../../logics/voice/useSettingsDraft";

export const WordFilter = (props) => {
    const { t } = useI18n();

    const [input_value, setInputValue] = useState("");
    const { currentMicWordFilterList, setMicWordFilterList } = useTranscription();
    const { currentIsOpenedMicWordFilterList, updateIsOpenedMicWordFilterList } = useStore_IsOpenedMicWordFilterList();

    const [error, setError] = useState(null);
    const form = useSettingsDraft(currentMicWordFilterList.data, error, setError, {
        write: setMicWordFilterList,
        label: () => t("config_page.transcription.mic_word_filter.label"),
    });
    const words = form.draft ?? currentMicWordFilterList.data;

    const listSectionRef = useRef(null);
    const shouldScrollToBottomRef = useRef(false);
    const entryRef = useRef(null);
    const deleteRefs = useRef(new Map());
    const pendingFocusRef = useRef(null);

    useEffect(() => {
        const pending = pendingFocusRef.current;
        if (!pending || words.includes(pending.word)) return;
        pendingFocusRef.current = null;
        // Do not take focus back if the user moved while the update settled.
        if (document.activeElement !== pending.button && document.activeElement !== document.body) return;
        const word = words[Math.min(pending.index, words.length - 1)];
        (deleteRefs.current.get(word) ?? entryRef.current)?.focus();
    }, [words]);

    const setListSectionRef = useCallback((node) => {
        listSectionRef.current = node;
        if (node) {
            node.scrollTop = node.scrollHeight;
            requestAnimationFrame(() => {
                if (listSectionRef.current) {
                    listSectionRef.current.scrollTop = listSectionRef.current.scrollHeight;
                }
            });
        }
    }, []);

    useEffect(() => {
        if (shouldScrollToBottomRef.current) {
            shouldScrollToBottomRef.current = false;
            requestAnimationFrame(() => {
                if (listSectionRef.current) {
                    listSectionRef.current.scrollTop = listSectionRef.current.scrollHeight;
                }
            });
        }
    }, [words, currentIsOpenedMicWordFilterList.data]);

    const onChangeEntry = (e) => {
        setInputValue(e.target.value);
    };

    const handleEnterPressed = () => {
        if (!input_value || !input_value.trim()) return;
        addWords();
    };

    const addWords = () => {
        if (input_value === undefined) return;
        const updated_list = [...words];
        for (const word of input_value.split(",").map(value => value.trim())) {
            if (word && !updated_list.includes(word)) updated_list.push(word);
        }
        if (updated_list.length !== words.length) {
            form.setDraft(updated_list);
            shouldScrollToBottomRef.current = true;
        }
        updateIsOpenedMicWordFilterList(true);
        setInputValue("");
    };

    const deleteAction = (target_item_value, button) => {
        pendingFocusRef.current = { word: target_item_value, button,
            index: words.indexOf(target_item_value) };
        form.setDraft(words.filter(item => item !== target_item_value));
    };


    return (
        <div className={styles.container}>
            {form.navigationDialog}
            { currentIsOpenedMicWordFilterList.data && words.length > 0 &&
                <div ref={setListSectionRef} className={styles.list_section_wrapper}>
                    {
                        words.map((item) => {
                            return <WordFilterItem value={item} key={item} deleteAction={deleteAction}
                                buttonRef={node => {
                                    if (node) deleteRefs.current.set(item, node);
                                    else deleteRefs.current.delete(item);
                                }}/>;
                        })
                    }
                </div>
            }
            <div className={styles.entry_section_wrapper}>
                <_Entry ref={entryRef} aria-describedby={props["aria-describedby"]} aria-label={t("config_page.transcription.mic_word_filter.label")} width="30rem" onChange={onChangeEntry} onEnterPressed={handleEnterPressed} ui_variable={input_value}/>
                <button className={styles.add_button} onClick={addWords}>{t("config_page.transcription.mic_word_filter.add_button_label")}</button>
            </div>
        </div>
    );
};

import DeleteSvg from "@images/cancel.svg?react";
import clsx from "clsx";
const WordFilterItem = (props) => {
    const { t } = useI18n();
    const item_wrapper_class_names = clsx(styles["item_wrapper"]);
    const item_text_class_names = clsx(styles["item_text"]);

    return (
        <div className={item_wrapper_class_names}>
            <p className={item_text_class_names}>{props.value}</p>
            <button type="button" ref={props.buttonRef} className={clsx(styles.action_button, styles.delete)}
                aria-label={t("config_page.transcription.mic_word_filter.remove_word", { word: props.value })}
                onClick={event => props.deleteAction(props.value, event.currentTarget)}>
                <DeleteSvg className={styles.delete_svg} aria-hidden="true" focusable="false"/>
            </button>
        </div>
    );
};

import ArrowLeftSvg from "@images/arrow_left.svg?react";
export const WordFilterListToggleComponent = (props) => {
    const { t } = useI18n();
    const { currentIsOpenedMicWordFilterList, updateIsOpenedMicWordFilterList } = useStore_IsOpenedMicWordFilterList();
    const { currentMicWordFilterList } = useTranscription();

    const svg_class_names = clsx(styles["arrow_left_svg"], {
        [styles.to_down]: !currentIsOpenedMicWordFilterList.data,
        [styles.to_up]: currentIsOpenedMicWordFilterList.data
    });

    const OnclickFunction = () => {
        updateIsOpenedMicWordFilterList(!currentIsOpenedMicWordFilterList.data);
    };

    return (
        <div className={styles.toggle_button_container}>
            <p className={styles.words_count_text}>{t("config_page.transcription.mic_word_filter.count_desc", {count: currentMicWordFilterList.data.length} )}</p>
            <button type="button" className={styles.toggle_button_wrapper} onClick={OnclickFunction}
                aria-describedby={props["aria-describedby"]}
                aria-expanded={currentIsOpenedMicWordFilterList.data === true}
                aria-label={t("config_page.transcription.mic_word_filter.count_desc", {count: currentMicWordFilterList.data.length})}>
                <ArrowLeftSvg className={svg_class_names} aria-hidden="true"/>
            </button>
        </div>
    );
};
