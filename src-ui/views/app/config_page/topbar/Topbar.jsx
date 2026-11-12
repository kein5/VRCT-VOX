import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import styles from "./Topbar.module.scss";
import { useIsOpenedConfigPage } from "@logics_common";
import { useSaveBarEntries } from "../../../../logics/voice/saveBar";
import { StopActions } from "../../others/stop_actions/StopActions";
import ArrowLeftSvg from "@images/arrow_left.svg?react";

// Save and discard for every settings form on the open page, so the save
// button is always in the same place. The bar counts the changes; the page
// marks the changed rows, and the names are in the tooltip and for screen readers.
export const SaveBar = () => {
    const { t } = useI18n();
    const entries = useSaveBarEntries();
    const dirty = entries.filter(entry => entry.dirty);
    const saving = entries.some(entry => entry.saving);
    // Only edits ask before leaving; a pending selection alone is dropped quietly.
    const guarded = entries.some(entry => entry.edited ?? entry.dirty) || saving;
    const [leaving, setLeaving] = useState(null);
    const dialog = useRef(null);
    // Leaving the page or settings with unsaved changes asks first, for every
    // form on the page. Capture runs before the voice forms' own guards, so
    // one dialog covers them all.
    useEffect(() => {
        if (!guarded) return;
        const guard = event => {
            if (event.defaultPrevented) return;
            event.preventDefault();
            setLeaving(() => event.detail.proceed);
        };
        window.addEventListener("vrct:settings-leave", guard, { capture: true });
        return () => window.removeEventListener("vrct:settings-leave", guard, { capture: true });
    }, [guarded]);
    useEffect(() => { if (leaving) dialog.current?.showModal(); }, [leaving]);
    const leaveDialog = leaving && <dialog ref={dialog} className={styles.leave_dialog} onCancel={() => setLeaving(null)}
        onClose={() => setLeaving(null)} aria-label={t("voice_ui.leave_title")}>
        <p>{t("voice_ui.leave_hint")}</p>
        <div className={styles.leave_actions}>
            <button type="button" autoFocus onClick={() => dialog.current?.close()}>{t("voice_ui.keep_editing")}</button>
            <button type="button" onClick={() => {
                const proceed = leaving;
                dirty.forEach(entry => entry.discard());
                dialog.current?.close();
                proceed();
            }}>{t("voice_ui.discard_leave")}</button>
        </div>
    </dialog>;
    if (!entries.length) return leaveDialog || null;
    const failed = entries.some(entry => entry.saveState === "save_failed");
    const changes = [...new Set(dirty.flatMap(entry => entry.changes))];
    // A page can propose a change the user has not made (the RVC page selects RVC).
    // Calling that "unsaved changes" reads as if something was edited; it is
    // something that Save will apply, and the bar says so.
    const proposed = dirty.length > 0 && !dirty.some(entry => entry.edited ?? entry.dirty);
    const state = saving ? "saving" : failed ? "save_failed" : proposed ? "applies_on_save" : dirty.length ? "unsaved" : "saved";
    const count = Math.max(changes.length, dirty.length);
    return <div className={clsx(styles.save_bar, { [styles.is_dirty]: dirty.length > 0 })} role="region" aria-label={t("voice_ui.save_bar")}>
        <div className={styles.summary} title={changes.length ? changes.join("\n") : undefined}>
            <span role="status" className={clsx(styles.state, { [styles.is_failed]: failed })}>{t(`voice_ui.${state}`, { changes: changes.join(t("voice_ui.changes_separator")) })}</span>
            {state === "unsaved" && <span className={styles.count} aria-hidden="true">{t("voice_ui.unsaved_count", { count })}</span>}
            {changes.length > 0 && <ul className={styles.changes} aria-label={t("voice_ui.changed_items")}>
                {changes.map(change => <li key={change}>{change}</li>)}
            </ul>}
        </div>
        {/* Narrow windows draw data-short instead; the text and the accessible name stay the full words. */}
        <button type="button" className={styles.discard} disabled={saving || !dirty.length} aria-label={t("voice_ui.discard")}
            data-short={t("voice_ui.discard_short")} onClick={() => dirty.forEach(entry => entry.discard())}>{t("voice_ui.discard")}</button>
        <button type="button" className={styles.save} disabled={saving || !dirty.length || dirty.some(entry => !entry.canSave)}
            aria-label={t(saving ? "voice.saving" : "voice_ui.save_changes")} data-short={t(saving ? "voice.saving" : "voice_ui.save_changes_short")}
            onClick={() => dirty.forEach(entry => entry.save())}>{t(saving ? "voice.saving" : "voice_ui.save_changes")}</button>
        {leaveDialog}
    </div>;
};

export const Topbar = () => {
    const { t } = useI18n();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();
    return <div className={styles.container}>
        <StopActions classes={styles} />
        {/* The save state keeps its slot on pages without forms, so the stop actions stay put. */}
        <div className={styles.save_slot}><SaveBar /></div>
        <button type="button" className={styles.back} aria-label={t("common.go_back_button_label")} onClick={() => setIsOpenedConfigPage(false)}>
            <ArrowLeftSvg aria-hidden="true" />
            <span className={styles.back_label} aria-hidden="true">{t("common.go_back_button_label")}</span>
        </button>
    </div>;
};
