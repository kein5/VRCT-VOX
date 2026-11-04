import { useI18n } from "@useI18n";
import styles from "./WordFilter.module.scss";
import { _Entry } from "../_atoms/_entry/_Entry";
import { useState, useRef, useEffect, useCallback } from "react";
import { useStore_IsOpenedMicWordFilterList } from "@store";
import { useTranscription } from "@logics_configs";

export const WordFilter = (props) => {
    const { t } = useI18n();

    const [input_value, setInputValue] = useState("");
    const { currentMicWordFilterList, updateMicWordFilterList, setMicWordFilterList } = useTranscription();
    const { currentIsOpenedMicWordFilterList, updateIsOpenedMicWordFilterList } = useStore_IsOpenedMicWordFilterList();

    const listSectionRef = useRef(null);
    const shouldScrollToBottomRef = useRef(false);
    const entryRef = useRef(null);
    const deleteRefs = useRef(new Map());
    const pendingFocusRef = useRef(null);

    useEffect(() => {
        const pending = pendingFocusRef.current;
        if (!pending || currentMicWordFilterList.data.includes(pending.word)) return;
        pendingFocusRef.current = null;
        // Do not take focus back if the user moved while the update settled.
        if (document.activeElement !== pending.button && document.activeElement !== document.body) return;
        const words = currentMicWordFilterList.data;
        const word = words[Math.min(pending.index, words.length - 1)];
        (deleteRefs.current.get(word) ?? entryRef.current)?.focus();
    }, [currentMicWordFilterList.data]);

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
    }, [currentMicWordFilterList.data, currentIsOpenedMicWordFilterList.data]);

    const onChangeEntry = (e) => {
        setInputValue(e.target.value);
    };

    const handleEnterPressed = () => {
        if (!input_value || !input_value.trim()) return;
        addWords();
    };

    const addWords = () => {
        if (input_value === undefined) return;
        let added = false;
        updateMicWordFilterList((prev_list) => {
            const input_value_array = input_value.split(",");
            let updated_list = [...prev_list.data];
            for (let each_input_value of input_value_array) {
                each_input_value = each_input_value.trim();
                if (each_input_value) {
                    const exists = updated_list.find((item) => item === each_input_value);
                    if (!exists) {
                        updated_list = [...updated_list, each_input_value];
                        added = true;
                    }
                }
            }
            if (added) {
                setMicWordFilterList(updated_list);
            }
            return updated_list;
        });

        if (added) {
            shouldScrollToBottomRef.current = true;
        }
        updateIsOpenedMicWordFilterList(true);
        setInputValue("");
    };


    const deleteAction = (target_item_value, button) => {
        pendingFocusRef.current = { word: target_item_value, button,
            index: currentMicWordFilterList.data.indexOf(target_item_value) };
        updateMicWordFilterList((prev_list) => {
            const updated_list = prev_list.data.filter((item) => item !== target_item_value);
            setMicWordFilterList(updated_list);
            return updated_list;
        });
    };


    return (
        <div className={styles.container}>
            { currentIsOpenedMicWordFilterList.data && currentMicWordFilterList.data.length > 0 &&
                <div ref={setListSectionRef} className={styles.list_section_wrapper}>
                    {
                        currentMicWordFilterList.data.map((item) => {
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
