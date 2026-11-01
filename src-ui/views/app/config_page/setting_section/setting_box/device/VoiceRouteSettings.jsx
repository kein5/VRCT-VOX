import { useEffect } from "react";
import { useI18n } from "@useI18n";
import { useStore_SelectedConfigTabId } from "@store";
import { useVoice } from "../../../../../../logics/voice/useVoice";
import { useSettingsDraft } from "../../../../../../logics/voice/useSettingsDraft";
import { SectionLabelComponent } from "../_components/section_label_component/SectionLabelComponent";
import styles from "../advanced_settings/VoiceSettings.module.scss";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import { FormRow } from "../_components/form_row/FormRow";

export const VoiceRouteSummary = () => {
    const { t } = useI18n();
    const { settings } = useVoice();
    const { updateSelectedConfigTabId } = useStore_SelectedConfigTabId();
    return <div className={styles.actions}><span>{t("voice.routing")}: {settings ? t(`voice.routing_${settings.routing}`) : t("voice.loading")}</span>
        <button type="button" onClick={() => updateSelectedConfigTabId("device")}>{t("voice_ui.edit_route")}</button></div>;
};

export const VoiceRouteControls = () => {
    const { t } = useI18n();
    const { route, error, send } = useVoice();
    const problem = error || route.error;
    return <>
        <FormRow group label={t("voice_ui.mute_row")} description={t(route.managed ? "voice.mute_scope_managed" : "voice.mute_scope_external")}>
            <button type="button" onClick={() => send("/run/mute_voice")}>{t("voice.mute")}</button>
            <button type="button" disabled={!route.ready || route.pending || !route.requested_muted} onClick={() => send("/run/resume_voice")}>{t("voice.resume")}</button>
        </FormRow>
        <EnvReadout tone={route.error ? "failed" : route.preparing || route.pending || !route.ready || route.observed_muted == null ? "neutral" : route.observed_muted ? "warning" : "active"}>
            <p>{t(route.preparing ? "voice.preparing_microphone" : route.error ? "voice.gate_error" : route.pending ? "voice.gate_pending" : !route.ready || route.observed_muted == null ? "voice.gate_unknown" : route.observed_muted ? "voice.gate_muted" : "voice.gate_open")}</p>
        </EnvReadout>
        {problem && <p role="alert">{t(`voice_setup_errors.${problem}`, { defaultValue: problem })}</p>}
    </>;
};

export const VoiceRouteSettings = () => {
    const { t } = useI18n();
    const { settings, directState, directPending, error, updateError, send } = useVoice();
    const busy = !!directPending || directState.requested || directState.pending || directState.stopping || !directState.observation_id;
    const form = useSettingsDraft(settings, error, updateError, { label: ([key]) => t(`voice.${key}`, { defaultValue: key }),
        write: value => send("/set/data/voice_settings", value), canSave: !busy });
    useEffect(() => { send("/get/data/voice_settings"); }, [send]);
    return <section className={styles.container} aria-label={t("voice.routing")} data-setting-id="voice_route">
        <SectionLabelComponent label={t("voice.routing")} />
        <p>{t("voice_ui.route_hint")}</p>
        {form.draft && <form onSubmit={e => { e.preventDefault(); if (!busy && form.dirty) form.submit(value => send("/set/data/voice_settings", value)); }}>
            <label>{t("voice.routing")}<select aria-label={t("voice.routing")} value={form.draft.routing} disabled={busy || form.saving}
                onChange={e => form.setDraft({ ...form.draft, routing: e.target.value })}>
                <option value="external">{t("voice.routing_external")}</option><option value="managed">{t("voice.routing_managed")}</option>
            </select></label>
            {form.draft.routing === "managed" && <p>{t("voice.managed_hint")}</p>}
        </form>}
        {form.navigationDialog}
        <VoiceRouteControls />
    </section>;
};
