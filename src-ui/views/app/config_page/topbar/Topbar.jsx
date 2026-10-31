import clsx from "clsx";
import { useI18n } from "@useI18n";
import styles from "./Topbar.module.scss";
import { useIsOpenedConfigPage } from "@logics_common";
import { useSaveBarEntries } from "../../../../logics/voice/saveBar";
import ArrowLeftSvg from "@images/arrow_left.svg?react";

// Save and discard for every settings form on the open page, with the changed
// fields listed, so the save button is always in the same place.
export const SaveBar = () => {
    const { t } = useI18n();
    const entries = useSaveBarEntries();
    if (!entries.length) return null;
    const dirty = entries.filter(entry => entry.dirty);
    const saving = entries.some(entry => entry.saving);
    const failed = entries.some(entry => entry.saveState === "save_failed");
    const changes = [...new Set(dirty.flatMap(entry => entry.changes))];
    const state = saving ? "saving" : failed ? "save_failed" : dirty.length ? "unsaved" : "saved";
    return <div className={clsx(styles.save_bar, { [styles.is_dirty]: dirty.length > 0 })} role="region" aria-label={t("voice_ui.save_bar")}>
        <div className={styles.summary}>
            <span role="status" className={clsx(styles.state, { [styles.is_failed]: failed })}>{t(`voice_ui.${state}`)}</span>
            {changes.length > 0 && <ul className={styles.changes} aria-label={t("voice_ui.changed_items")} title={changes.join("\n")}>
                {changes.map(change => <li key={change}>{change}</li>)}
            </ul>}
        </div>
        <button type="button" className={styles.discard} disabled={saving || !dirty.length}
            onClick={() => dirty.forEach(entry => entry.discard())}>{t("voice_ui.discard")}</button>
        <button type="button" className={styles.save} disabled={saving || !dirty.length || dirty.some(entry => !entry.canSave)}
            onClick={() => dirty.forEach(entry => entry.save())}>{t(saving ? "voice.saving" : "voice_ui.save_changes")}</button>
    </div>;
};

export const Topbar = () => {
    const { t } = useI18n();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();
    return <div className={styles.container}>
        <SaveBar />
        <button type="button" className={styles.back} onClick={() => setIsOpenedConfigPage(false)}>
            <ArrowLeftSvg aria-hidden="true" />
            {t("common.go_back_button_label")}
        </button>
    </div>;
};
