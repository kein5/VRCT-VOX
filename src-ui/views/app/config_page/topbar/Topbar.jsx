import clsx from "clsx";
import { useI18n } from "@useI18n";
import styles from "./Topbar.module.scss";
import { useIsOpenedConfigPage } from "@logics_common";
import { useSaveBarEntries } from "../../../../logics/voice/saveBar";
import { useVoice } from "../../../../logics/voice/useVoice";
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

// Stop actions reachable from every settings page during a conversation. They
// send the same requests as the TTS page's stop and the route's mute, and never
// start, resume or reroute anything. Stop is quiet until there is speech to stop.
export const StopActions = () => {
    const { t } = useI18n();
    const { status, send } = useVoice();
    const queued = status.queued ?? 0;
    const speaking = !!status.active || queued > 0;
    return <div className={styles.stop_actions} role="group" aria-label={t("voice_ui.stop_actions")}>
        <button type="button" className={clsx(styles.stop, { [styles.is_attention]: speaking })} title={t("voice.stop")}
            onClick={() => send("/run/stop_voice")}>
            {t("voice_ui.topbar_stop")}{queued > 0 && <span className={styles.count}>{t("voice_ui.topbar_queued", { count: queued })}</span>}
        </button>
        <button type="button" className={styles.stop} title={t("voice.mute")} onClick={() => send("/run/mute_voice")}>{t("voice_ui.topbar_mute")}</button>
    </div>;
};

export const Topbar = () => {
    const { t } = useI18n();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();
    return <div className={styles.container}>
        <StopActions />
        <SaveBar />
        <button type="button" className={styles.back} onClick={() => setIsOpenedConfigPage(false)}>
            <ArrowLeftSvg aria-hidden="true" />
            {t("common.go_back_button_label")}
        </button>
    </div>;
};
