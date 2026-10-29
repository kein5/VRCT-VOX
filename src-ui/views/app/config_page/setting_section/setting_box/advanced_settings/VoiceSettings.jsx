import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useVoice } from "../../../../../../logics/voice/useVoice";
import styles from "./VoiceSettings.module.scss";
import { DirectVoiceSettings } from "./DirectVoiceSettings";
import { SpeechServers } from "./SpeechServers";

export const VoiceSettings = () => {
    const { t } = useI18n();
    const { settings, status, route, devices, error, send, updateError } = useVoice();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    useEffect(() => {
        send("/get/data/voice_settings");
        send("/get/data/voice_output_devices");
        send("/get/data/voice_status");
        send("/get/data/voice_route");
        const timer = setInterval(() => {
            send("/get/data/voice_status");
            send("/get/data/voice_route");
        }, 1000);
        return () => clearInterval(timer);
    }, [send]);
    useEffect(() => { setDraft(settings); setSaving(false); }, [settings]);
    useEffect(() => { if (error) setSaving(false); }, [error]);
    useEffect(() => {
        if (!saving) return;
        const timer = setTimeout(() => { setSaving(false); updateError("save_unconfirmed"); }, 5000);
        return () => clearTimeout(timer);
    }, [saving, updateError]);
    if (!draft) return <div>
        <p role="status">{error ? t("voice.error") : t("voice.loading")}</p>
        <button type="button" onClick={() => send("/get/data/voice_settings")}>{t("voice.retry")}</button>
    </div>;
    const field = (key, value) => setDraft(previous => ({ ...previous, [key]: value }));
    const input = key => <label>{t(`voice.${key}`)}
        <input value={draft[key]} onChange={e => field(key, e.target.value)} maxLength={key.endsWith("voice") ? 128 : 512} />
    </label>;
    const server = role => <label>{t(`speech_servers.${role}_selection`)}
        <select aria-label={t(`speech_servers.${role}_selection`)} value={draft[`${role}_server`] || "external"} onChange={e => field(`${role}_server`, e.target.value)}>
            {["external", "bundled"].map(value => <option key={value} value={value}>{t(`speech_servers.${value}`)}</option>)}
        </select>
    </label>;
    const deviceList = devices.devices || [];
    return <section className={styles.container} aria-label={t("voice.title")}>
        <h3>{t("voice.title")}</h3>
        <p>{t("voice.description")}</p>
        <form onSubmit={e => {
            e.preventDefault();
            setSaving(true);
            send("/set/data/voice_settings", draft);
        }}>
            <label>{t("voice.mode")}
                <select value={draft.mode} onChange={e => field("mode", e.target.value)}>
                    {["off", "original", "translated"].map(mode => <option key={mode} value={mode}>{t(`voice.${mode}`)}</option>)}
                </select>
            </label>
            <label>{t("voice.mic_mode")}
                <select value={draft.mic_mode || "off"} onChange={e => field("mic_mode", e.target.value)}>
                    <option value="off">{t("voice.off")}</option>
                    <option value="translated">{t("voice.mic_translated")}</option>
                </select>
            </label>
            <label>{t("voice.direct_policy")}
                <select disabled={draft.mic_mode !== "translated"} value={draft.direct_policy || "suppress"}
                    onChange={e => field("direct_policy", e.target.value)}>
                    <option value="suppress">{t("voice.direct_suppress")}</option>
                    <option value="mix">{t("voice.direct_mix")}</option>
                </select>
            </label>
            <p>{t("voice.mic_hint")}</p>
            <label>{t("voice.target_slot")}
                <select value={draft.target_slot} onChange={e => field("target_slot", e.target.value)}>
                    {["1", "2", "3"].map(slot => <option key={slot}>{slot}</option>)}
                </select>
            </label>
            <label>{t("voice.output_device")}
                <select disabled={draft.routing === "managed"} value={draft.output_device} onChange={e => field("output_device", e.target.value)}>
                    <option value="">{t("voice.select_output")}</option>
                    {draft.output_device && !deviceList.some(d => d.id === draft.output_device) &&
                        <option value={draft.output_device}>{t("voice.disconnected")}: {draft.output_device}</option>}
                    {deviceList.map(device => <option key={device.id} value={device.id}>{device.label}</option>)}
                </select>
            </label>
            <label>{t("voice.routing")}
                <select value={draft.routing || "external"} onChange={e => field("routing", e.target.value)}>
                    <option value="external">{t("voice.routing_external")}</option>
                    <option value="managed">{t("voice.routing_managed")}</option>
                </select>
            </label>
            {draft.routing === "managed" && <p>{t("voice.managed_hint")}</p>}
            <button type="button" onClick={() => send("/get/data/voice_output_devices")}>{t("voice.refresh")}</button>
            {server("japanese")}{draft.japanese_server !== "bundled" && input("japanese_url")}{input("japanese_voice")}
            {server("multilingual")}{draft.multilingual_server !== "bundled" && input("multilingual_url")}{input("multilingual_voice")}
            <p>{t("voice.routing_hint")}</p>
            <button type="submit" disabled={saving}>{t(saving ? "voice.saving" : "voice.save")}</button>
            <button type="button" onClick={() => send("/run/stop_voice")}>{t("voice.stop")}</button>
        </form>
        <SpeechServers />
        <DirectVoiceSettings />
        <p>{t(route.managed ? "voice.mute_scope_managed" : "voice.mute_scope_external")}</p>
        <button type="button" onClick={() => send("/run/mute_voice")}>{t("voice.mute")}</button>
        <button type="button" disabled={!route.ready || route.pending || !route.requested_muted}
            onClick={() => send("/run/resume_voice")}>{t("voice.resume")}</button>
        <p role="status">{t(route.error ? "voice.gate_error" : route.pending ? "voice.gate_pending" :
            !route.ready || route.observed_muted == null ? "voice.gate_unknown" :
                route.observed_muted ? "voice.gate_muted" : "voice.gate_open")}</p>
        <p role="status">{t(status.active ? "voice.playing" : "voice.idle")} · {t("voice.queued")}: {status.queued ?? 0}</p>
        {status.dropped > 0 && <p>{t("voice.dropped", { count: status.dropped })}</p>}
        {(error || route.error || status.last_error || devices.error) &&
            <p role="alert">{t("voice.error")}: {error || route.error || status.last_error || devices.error}</p>}
    </section>;
};
