import { useRef, useLayoutEffect, useEffect } from "react";

import styles from "./SettingSection.module.scss";
import { SettingBox } from "./setting_box/SettingBox";
import { store, useStore_SelectedConfigTabId } from "@store";
import { useSettingBoxScrollPosition } from "@logics_configs";
import { useSaveBarEntries } from "../../../../logics/voice/saveBar";

// The top bar only counts unsaved changes; the rows they belong to are marked
// here. Changes are named by their row labels, so a row matches by its label:
// template rows and FormRow carry data-setting-label, and the voice forms' plain
// <label> rows start with their label text. Rows re-render freely, so the marks
// are reapplied whenever the page's DOM changes.
const markUnsavedRows = (root, names) => {
    root.querySelectorAll("[data-setting-label]").forEach(row => {
        row.toggleAttribute("data-unsaved", names.has(row.dataset.settingLabel));
    });
    root.querySelectorAll("label").forEach(row => {
        if (row.closest("[data-setting-label]")) return;
        const text = row.firstChild?.nodeType === Node.TEXT_NODE ? row.firstChild.textContent.trim() : null;
        row.toggleAttribute("data-unsaved", text !== null && names.has(text));
    });
};

const useUnsavedRowMarks = (ref) => {
    const entries = useSaveBarEntries();
    const key = JSON.stringify([...new Set(entries.filter(entry => entry.dirty).flatMap(entry => entry.changes))]);
    useEffect(() => {
        const root = ref.current;
        if (!root) return;
        const names = new Set(JSON.parse(key));
        markUnsavedRows(root, names);
        const observer = new MutationObserver(() => markUnsavedRows(root, names));
        observer.observe(root, { childList: true, subtree: true, characterData: true });
        return () => observer.disconnect();
    }, [ref, key]);
};

export const SettingSection = () => {
    const { currentSelectedConfigTabId } = useStore_SelectedConfigTabId();
    const { resetScrollPosition } = useSettingBoxScrollPosition();
    const scrollContainerRef = useRef(null);
    useUnsavedRowMarks(scrollContainerRef);

    useLayoutEffect(() => {
        store.setting_box_scroll_container = scrollContainerRef;
    }, []);

    useEffect(() => {
        resetScrollPosition();
    }, [currentSelectedConfigTabId.data]);

    return (
        <div ref={scrollContainerRef} className={styles.scroll_container}>
            <div className={styles.container}>
                <SettingBox />
            </div>
        </div>
    );
};