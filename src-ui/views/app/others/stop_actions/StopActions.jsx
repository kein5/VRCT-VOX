import clsx from "clsx";
import { useEffect } from "react";
import { useI18n } from "@useI18n";
import { useVoice } from "../../../../logics/voice/useVoice";
import { voiceActions } from "../../../../logics/voice/voiceActions.js";

// Stop actions within reach during a conversation: on the main page and on
// every settings page. Stop sends the TTS page's stop (it also clears the
// queue). Mute is the route's mute: TTS on the external route, and the whole
// virtual microphone (TTS and converted voice) on the managed route, so it is
// named by what it silences. It shows the reported mute state as a pressed
// toggle; pressing it again asks to resume, which the backend allows only once
// the route is ready.
// classes: the host bar's stylesheet (stop_actions, stop, long, short,
// is_attention, is_pressed, muted_badge); each bar places and sizes them. A bar
// with a `tiny` class also gets the shortest words, for its narrowest layout.
export const StopActions = ({ classes }) => {
    const { t } = useI18n();
    const { status, route, send } = useVoice();
    useEffect(() => { send("/get/data/voice_status"); send("/get/data/voice_route"); }, [send]);
    const queued = status.queued ?? 0;
    const speaking = !!status.active || queued > 0;
    const stop = queued > 0 ? t("voice_ui.topbar_stop_count", { count: queued }) : t("voice_ui.topbar_stop");
    const stopShort = queued > 0 ? t("voice_ui.topbar_stop_short_count", { count: queued }) : t("voice_ui.topbar_stop_short");
    const stopTiny = queued > 0 ? t("voice_ui.topbar_stop_tiny_count", { count: queued }) : t("voice_ui.topbar_stop_tiny");
    // Only a reported state makes a toggle; without one this is a plain mute action.
    const known = typeof route.requested_muted === "boolean";
    const muted = known && route.requested_muted;
    const coversVoice = route.managed || route.covers_direct;
    const mute = t(coversVoice ? "voice_ui.topbar_mute_mic" : "voice_ui.topbar_mute_speech");
    const resumeBlocked = muted && (!route.ready || route.pending);
    const stopVoice = () => send("/run/stop_voice");
    const toggleMute = () => { if (!resumeBlocked) send(muted ? "/run/resume_voice" : "/run/mute_voice"); };
    // Hotkeys press these same buttons, with today's state (logics/voice/voiceActions.js).
    useEffect(() => { voiceActions.stop = stopVoice; voiceActions.toggleMute = toggleMute; });
    return <div className={classes.stop_actions} role="group" aria-label={t("voice_ui.stop_actions")}>
        {/* Narrow windows show the short words, which stay part of the accessible name. */}
        <button type="button" className={clsx(classes.stop, { [classes.is_attention]: speaking })} title={t("voice.stop")}
            aria-label={stop} onClick={stopVoice}>
            <span className={classes.long} aria-hidden="true">{stop}</span>
            <span className={classes.short} aria-hidden="true">{stopShort}</span>
            {classes.tiny && <span className={classes.tiny} aria-hidden="true">{stopTiny}</span>}
        </button>
        <button type="button" className={clsx(classes.stop, { [classes.is_pressed]: muted })} aria-label={mute}
            aria-pressed={known ? muted : undefined} title={t(route.managed ? "voice.mute_scope_managed" : route.covers_direct ? "voice.mute_scope_device" : "voice.mute_scope_external")}
            disabled={resumeBlocked}
            onClick={toggleMute}>
            <span className={classes.long} aria-hidden="true">{mute}</span>
            <span className={classes.short} aria-hidden="true">{t("voice_ui.topbar_mute_short")}</span>
            {classes.tiny && <span className={classes.tiny} aria-hidden="true">{t(muted ? "voice_ui.topbar_muted" : "voice_ui.topbar_mute_short")}</span>}
            {muted && <span className={classes.muted_badge} aria-hidden="true">{t("voice_ui.topbar_muted")}</span>}
        </button>
    </div>;
};
