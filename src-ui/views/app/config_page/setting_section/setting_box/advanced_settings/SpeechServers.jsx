import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useSpeechServers } from "../../../../../../logics/voice/useSpeechServers";
import { useSettingsDraft } from "../../../../../../logics/voice/useSettingsDraft";
import styles from "./VoiceSettings.module.scss";
import { ModelDownloads, HardwareReadout } from "./ModelDownloads";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import { Description } from "../_components/description/Description";

// Readout tone for a server state; the state text itself always says it.
const serverTone = (owner, pending) => pending || ["preparing", "stopping"].includes(owner?.state) ? "warning" :
    owner?.error_code || owner?.state === "failed" ? "failed" : owner?.state === "ready" ? "active" : "neutral";

export const SpeechServers = ({ profiles = ["japanese", "multilingual", "asr"] }) => {
    const { t } = useI18n();
    const { settings, state, pending, error, send, updateError } = useSpeechServers();
    // Paths are ["profiles", name, key]; a page shows only its own profiles.
    const label = ([, name, key]) => `${t(`speech_servers.${name}`)}: ${t(`speech_servers.${key}`, { defaultValue: key })}`;
    const form = useSettingsDraft(settings, error, updateError, { label,
        write: value => send("/set/data/speech_server_settings", value) });
    const { draft, setDraft, saving, dirty } = form;
    const pendingKey = JSON.stringify(pending);
    // One-time setup stays folded; the summary says enough to leave it so.
    const [opened, setOpened] = useState(false);
    // TTS engines on one page share one GPU/memory reading and headroom choice.
    const [reserve, setReserve] = useState('vr');
    const tts = profiles.some(name => ["japanese", "multilingual"].includes(name));
    useEffect(() => {
        send("/get/data/speech_server_settings");
        send("/get/data/speech_server_state");
    }, [send]);
    useEffect(() => {
        if (!Object.keys(pending).length) return;
        const timer = setTimeout(() => { updateError("speech_server_request_unconfirmed"); }, 5000);
        return () => clearTimeout(timer);
    }, [saving, pendingKey, updateError]);
    const field = (name, key, value) => setDraft(previous => ({ ...previous,
        profiles: { ...previous.profiles, [name]: { ...previous.profiles[name], [key]: value } } }));
    const stateText = name => t(`speech_servers.state_${pending[name] ? "pending" : state[name]?.state ?? "unknown"}`);
    const configured = name => {
        const saved = settings?.profiles?.[name];
        return !!saved?.model?.trim() && (name !== "asr" || !!saved?.vad_model?.trim());
    };
    // Open by itself only when a server reports an error to fix in here.
    const attention = profiles.some(name => !!state[name]?.error_code || !!state[name]?.low_latency?.error_code);
    const summary = profiles.map(name => `${t(`speech_servers.${name}`)}: ${t(configured(name) ? "speech_servers.model_set" : "speech_servers.model_unset")} · ${stateText(name)}`).join(" / ");
    return <section className={styles.container} aria-label={t("speech_servers.title")}>
        <details className={styles.setup} open={opened || attention} onToggle={event => setOpened(event.currentTarget.open)}>
        <summary><span className={styles.setupTitle}>{t("speech_servers.setup_title")}</span><span className={styles.setupStatus}>{summary}</span></summary>
        <div className={styles.setupBody}>
        <Description text={t("speech_servers.help")} />
        {tts && <HardwareReadout reserve={reserve} setReserve={setReserve} />}
        {draft && <form onSubmit={event => {
            event.preventDefault(); if (dirty) form.submit(value => send("/set/data/speech_server_settings", value));
        }}>
            {profiles.map(name => {
                const row = draft.profiles[name], owner = state[name];
                const busy = saving || !!pending[name] || !owner || ["preparing", "ready", "stopping"].includes(owner.state);
                const input = key => <label key={key}>{t(`speech_servers.${key}`)}
                    <input value={row[key]} disabled={busy} maxLength={4096} spellCheck={false}
                        onChange={event => field(name, key, event.target.value)} />
                </label>;
                return <fieldset key={name}>
                    <legend>{t(`speech_servers.${name}`)}</legend>
                    {input("model")}{input(name === "asr" ? "vad_model" : "voice_file")}
                    {/* Other unsaved edits survive an apply; only an edited model path conflicts. */}
                    {/* The asr profile also takes a VAD file; "expected" names the field each target replaces. */}
                    <ModelDownloads targets={name === "asr" ? ["asr", "vad"] : [name]} deviceMode={settings.profiles[name].device}
                        reserve={name === "asr" ? undefined : reserve}
                        blocked={busy ? "busy" : row.model !== settings.profiles[name].model ||
                            (name === "asr" && row.vad_model !== settings.profiles.asr.vad_model) ? "edited" : false}
                        expected={name === "asr" ? { asr: { model: settings.profiles.asr.model }, vad: { model: settings.profiles.asr.vad_model } }
                            : { [name]: { model: settings.profiles[name].model } }} />
                    <label>{t("speech_servers.device")}<select aria-label={t("speech_servers.device")} value={row.device} disabled={busy}
                        onChange={event => field(name, "device", event.target.value)}>
                        {["auto", "cpu", "gpu"].map(device => <option key={device} value={device}>{t(`speech_servers.${device}`)}</option>)}
                    </select></label>
                    {name === "japanese" && <>
                        <label className={styles.checkLabel}><input type="checkbox" checked={!!row.low_latency} disabled={busy}
                            onChange={event => field(name, "low_latency", event.target.checked)} />{t("speech_servers.low_latency")}</label>
                        <Description text={t("speech_servers.low_latency_help")} />
                    </>}
                    <div className={styles.actions}><button type="button" className="primary" disabled={dirty || saving || busy || !row.model.trim() ||
                        (name === "asr" && !row.vad_model.trim()) || owner?.error_code === "speech_server_cleanup_unconfirmed"}
                        onClick={() => send("/run/start_speech_server", { profile: name, generation: owner.generation })}>{t("speech_servers.start")}</button>
                    <button type="button" className={styles.quiet} onClick={() => send("/run/stop_speech_server", { profile: name })}>{t("speech_servers.stop")}</button></div>
                    <EnvReadout tone={serverTone(owner, pending[name])}>
                        <p>{stateText(name)}</p>
                        {owner?.low_latency && <p>{t(`speech_servers.low_latency_${owner.low_latency.state}`)}</p>}
                    </EnvReadout>
                    {owner?.low_latency?.error_code && <p role="alert">{t("speech_servers.low_latency_failed")}</p>}
                    {owner?.error_code && <p role="alert">{owner.error_code === "speech_server_out_of_memory" && <>{t("voice_ui.memory_error")} </>}{owner.error_code}</p>}
                </fieldset>;
            })}
        </form>}
        <button type="button" disabled={dirty || saving} onClick={() => { send("/get/data/speech_server_settings"); send("/get/data/speech_server_state"); }}>{t("speech_servers.reload")}</button>
        </div>
        </details>
        {/* The unsaved-changes dialog stays outside the fold so it shows while folded. */}
        {form.navigationDialog}
        {error && <p role="alert">{error}</p>}
    </section>;
};
