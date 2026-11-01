import clsx from "clsx";
import { useEffect } from "react";
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

// Stop actions reachable from every settings page during a conversation. Stop
// sends the TTS page's stop (it also clears the queue). Mute is the route's
// mute: TTS on the external route, and the whole virtual microphone (TTS and
// converted voice) on the managed route, so it is named by what it silences.
// It shows the reported mute state as a pressed toggle; pressing it again asks
// to resume, which the backend allows only once the route is ready.
export const StopActions = () => {
    const { t } = useI18n();
    const { status, route, send } = useVoice();
    useEffect(() => { send("/get/data/voice_status"); send("/get/data/voice_route"); }, [send]);
    const queued = status.queued ?? 0;
    const speaking = !!status.active || queued > 0;
    const stop = queued > 0 ? t("voice_ui.topbar_stop_count", { count: queued }) : t("voice_ui.topbar_stop");
    const stopShort = queued > 0 ? t("voice_ui.topbar_stop_short_count", { count: queued }) : t("voice_ui.topbar_stop_short");
    // Only a reported state makes a toggle; without one this is a plain mute action.
    const known = typeof route.requested_muted === "boolean";
    const muted = known && route.requested_muted;
    const mute = t(route.managed ? "voice_ui.topbar_mute_mic" : "voice_ui.topbar_mute_speech");
    return <div className={styles.stop_actions} role="group" aria-label={t("voice_ui.stop_actions")}>
        {/* Narrow windows show the short words, which stay part of the accessible name. */}
        <button type="button" className={clsx(styles.stop, { [styles.is_attention]: speaking })} title={t("voice.stop")}
            aria-label={stop} onClick={() => send("/run/stop_voice")}>
            <span className={styles.long} aria-hidden="true">{stop}</span>
            <span className={styles.short} aria-hidden="true">{stopShort}</span>
        </button>
        <button type="button" className={clsx(styles.stop, { [styles.is_pressed]: muted })} aria-label={mute}
            aria-pressed={known ? muted : undefined} title={t(route.managed ? "voice.mute_scope_managed" : "voice.mute_scope_external")}
            disabled={muted && (!route.ready || route.pending)}
            onClick={() => send(muted ? "/run/resume_voice" : "/run/mute_voice")}>
            <span className={styles.long} aria-hidden="true">{mute}</span>
            <span className={styles.short} aria-hidden="true">{t("voice_ui.topbar_mute_short")}</span>
            {muted && <span className={styles.state} aria-hidden="true">{t("voice_ui.topbar_muted")}</span>}
        </button>
    </div>;
};

export const Topbar = () => {
    const { t } = useI18n();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();
    return <div className={styles.container}>
        <StopActions />
        {/* The save state keeps its slot on pages without forms, so the stop actions stay put. */}
        <div className={styles.save_slot}><SaveBar /></div>
        <button type="button" className={styles.back} onClick={() => setIsOpenedConfigPage(false)}>
            <ArrowLeftSvg aria-hidden="true" />
            {t("common.go_back_button_label")}
        </button>
    </div>;
};
