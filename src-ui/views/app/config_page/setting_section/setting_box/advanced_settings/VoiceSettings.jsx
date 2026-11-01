import { useEffect } from "react";
import { useI18n } from "@useI18n";
import { useVoice } from "../../../../../../logics/voice/useVoice";
import { useSettingsDraft } from "../../../../../../logics/voice/useSettingsDraft";
import { GenerationOptions, validGenerationOptions } from "../tts/GenerationOptions";
import { VoiceRouteSummary } from "../device/VoiceRouteSettings";
import { SectionLabelComponent } from "../_components/section_label_component/SectionLabelComponent";
import { StatusLine } from "./StatusLine";
import styles from "./VoiceSettings.module.scss";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import { Description } from "../_components/description/Description";

export const VoiceSettings = () => {
    const { t } = useI18n();
    const { settings, status, devices, error, send, updateError } = useVoice();
    const label = ([key]) => {
        const role = ["japanese", "multilingual"].find(name => key.startsWith(`${name}_`));
        if (key === `${role}_server`) return t(`speech_servers.${role}_selection`);
        if (key === `${role}_seed`) return `${t(`speech_servers.${role}`)}: ${t("voice_ui.seed_mode")}`;
        if (key === `${role}_instructions`) return `${t(`speech_servers.${role}`)}: ${t("voice_ui.instruction")}`;
        return t(`voice.${key}`, { defaultValue: key });
    };
    const form = useSettingsDraft(settings, error, updateError, { label,
        write: value => send("/set/data/voice_settings", value), canSave: validGenerationOptions });
    const { draft, setDraft, saving } = form;
    useEffect(() => {
        send("/get/data/voice_settings");
        send("/get/data/voice_output_devices");
    }, [send]);
    if (!draft) return <div>
        <p role="status">{error ? t("voice.error") : t("voice.loading")}</p>
        <button type="button" onClick={() => send("/get/data/voice_settings")}>{t("voice.retry")}</button>
    </div>;
    const field = (key, value) => setDraft(previous => ({ ...previous, [key]: value }));
    const input = key => {
        const voice = key.endsWith("_voice");
        return <label>{t(`voice.${key}`)}
            <input value={voice && draft[key] === "none" ? "" : draft[key]} placeholder={voice ? t("voice_ui.voice_unset") : undefined}
                onChange={e => field(key, voice && e.target.value === "" ? "none" : e.target.value)} maxLength={voice ? 128 : 512} />
        </label>;
    };
    const server = role => <label>{t(`speech_servers.${role}_selection`)}
        <select aria-label={t(`speech_servers.${role}_selection`)} value={draft[`${role}_server`] || "external"} onChange={e => field(`${role}_server`, e.target.value)}>
            {["external", "bundled"].map(value => <option key={value} value={value}>{t(`speech_servers.${value}`)}</option>)}
        </select>
    </label>;
    const deviceList = devices.devices || [];
    // The monitor never offers the virtual microphone's own endpoints or output.
    const monitorList = deviceList.filter(d => !d.id.startsWith("vrct.") && d.id !== (draft.routing === "managed" ? "" : draft.output_device));
    return <section className={styles.container} aria-label={t("voice.title")} data-setting-id="tts_settings">
        <SectionLabelComponent label="TTS" />
        <StatusLine tone={status.active ? "active" : "idle"}
            actions={<button type="button" onClick={() => send("/run/stop_voice")}>{t("voice.stop")}</button>}>
            {t(status.active ? "voice.playing" : "voice.idle")} · {t("voice.queued")}: {status.queued ?? 0}
        </StatusLine>
        <Description text={t("voice_ui.tts_description")} />
        <VoiceRouteSummary />
        <form onSubmit={e => { e.preventDefault(); if (form.dirty && validGenerationOptions(draft)) form.submit(value => send("/set/data/voice_settings", value)); }}>
            <fieldset className={styles.fields} disabled={saving}>
                <label>{t("voice.mode")}<select aria-label={t("voice.mode")} value={draft.mode} onChange={e => field("mode", e.target.value)}>
                    {["off", "original", "translated"].map(mode => <option key={mode} value={mode}>{t(`voice.${mode}`)}</option>)}
                </select></label>
                <label>{t("voice.target_slot")}<select aria-label={t("voice.target_slot")} disabled={draft.mode !== "translated" && draft.mic_mode !== "translated"}
                    value={draft.target_slot} onChange={e => field("target_slot", e.target.value)}>
                    {["1", "2", "3"].map(slot => <option key={slot}>{slot}</option>)}
                </select></label>
                <label>{t("voice.output_device")}<select aria-label={t("voice.output_device")} disabled={draft.routing === "managed"} value={draft.output_device}
                    onChange={e => field("output_device", e.target.value)}>
                    <option value="">{t("voice.select_output")}</option>
                    {draft.output_device && !deviceList.some(d => d.id === draft.output_device) &&
                        <option value={draft.output_device}>{t("voice.disconnected")}: {draft.output_device}</option>}
                    {deviceList.map(device => <option key={device.id} value={device.id}>{device.label}</option>)}
                </select></label>
                <Description text={t("voice_ui.output_hint")} />
                <div className={styles.actions}><button type="button" onClick={() => send("/get/data/voice_output_devices")}>{t("voice.refresh")}</button></div>
                <fieldset className={styles.group} aria-label={t("voice.monitor")}>
                    <legend>{t("voice.monitor")}</legend>
                    <label>{t("voice.monitor")}<select aria-label={t("voice.monitor")} value={draft.monitor || "off"} onChange={e => field("monitor", e.target.value)}>
                        <option value="off">{t("voice.monitor_off")}</option><option value="on">{t("voice.monitor_on")}</option>
                    </select></label>
                    <label>{t("voice.monitor_device")}<select aria-label={t("voice.monitor_device")} disabled={draft.monitor !== "on"} value={draft.monitor_device || ""}
                        onChange={e => field("monitor_device", e.target.value)}>
                        <option value="">{t("voice.monitor_default")}</option>
                        {draft.monitor_device && !monitorList.some(d => d.id === draft.monitor_device) &&
                            <option value={draft.monitor_device}>{t("voice.disconnected")}: {draft.monitor_device}</option>}
                        {monitorList.map(device => <option key={device.id} value={device.id}>{device.label}</option>)}
                    </select></label>
                    <label>{t("voice.monitor_volume")}: {draft.monitor_volume ?? "100"}%<input type="range" min="0" max="100" step="5" aria-label={t("voice.monitor_volume")}
                        disabled={draft.monitor !== "on"} value={draft.monitor_volume ?? "100"} onChange={e => field("monitor_volume", String(e.target.value))} /></label>
                    <Description text={t("voice.monitor_hint")} />
                    {status.monitor_error && <EnvReadout tone="failed"><p>{t(`voice.monitor_errors.${status.monitor_error}`, { defaultValue: t("voice.monitor_error") })}</p></EnvReadout>}
                </fieldset>
                {["japanese", "multilingual"].map(role => <fieldset key={role} className={styles.group} aria-label={`${t(`speech_servers.${role}`)} · ${t("voice.title")}`}>
                    <legend>{t(`speech_servers.${role}`)}</legend>
                    {server(role)}{draft[`${role}_server`] !== "bundled" && input(`${role}_url`)}{input(`${role}_voice`)}
                    <GenerationOptions role={role} draft={draft} field={field} />
                </fieldset>)}
                <details><summary>{t("voice.mic_mode")}</summary>
                    <label>{t("voice.mic_mode")}<select aria-label={t("voice.mic_mode")} value={draft.mic_mode || "off"} onChange={e => field("mic_mode", e.target.value)}>
                        <option value="off">{t("voice.off")}</option><option value="translated">{t("voice.mic_translated")}</option>
                    </select></label>
                    <label>{t("voice.direct_policy")}<select aria-label={t("voice.direct_policy")} disabled={draft.mic_mode !== "translated"} value={draft.direct_policy || "suppress"}
                        onChange={e => field("direct_policy", e.target.value)}>
                        <option value="suppress">{t("voice.direct_suppress")}</option><option value="mix">{t("voice.direct_mix")}</option>
                    </select></label><Description text={t("voice.mic_hint")} />
                </details>
            </fieldset>
        </form>
        {!validGenerationOptions(draft) && <p role="alert">{t("voice_ui.invalid_options")}</p>}
        {form.navigationDialog}
        {(error || status.last_error || devices.error) && <p role="alert">{t("voice.error")}: {error || status.last_error || devices.error}</p>}
    </section>;
};
