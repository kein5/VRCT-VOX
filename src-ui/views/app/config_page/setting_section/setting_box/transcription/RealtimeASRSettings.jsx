import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useRealtimeASR } from "../../../../../../logics/transcription/useRealtimeASR";
import { useSpeechServers } from "../../../../../../logics/voice/useSpeechServers";
import styles from "../advanced_settings/VoiceSettings.module.scss";

const key = endpoint => endpoint ? JSON.stringify([endpoint.cookie, endpoint.serial, endpoint.name, endpoint.media_class]) : "";
// Select value for "follow the system default"; never a JSON endpoint key.
const FOLLOW = "follow-default";

export const RealtimeASRSettings = () => {
    const { t } = useI18n();
    const { settings, state, endpoints, models, error, send } = useRealtimeASR();
    const { state: servers, send: sendSpeech } = useSpeechServers();
    const [draft, setDraft] = useState(null);
    useEffect(() => { setDraft(settings); }, [settings]);
    const refreshDevices = () => {
        for (const source of ["mic", "speaker"]) send("/get/data/realtime_asr_endpoints", { source });
    };
    useEffect(() => {
        send("/get/data/realtime_asr_settings");
        send("/get/data/realtime_asr_state");
        sendSpeech("/get/data/speech_server_state");
        refreshDevices();
    }, [send, sendSpeech]);
    useEffect(() => {
        if (settings?.base_url) send("/get/data/realtime_asr_models");
    }, [settings?.base_url, settings?.server, servers.asr?.generation, servers.asr?.base_url, send]);
    const modelsCurrent = models.server === settings?.server && models.configured_url === settings?.base_url &&
        (settings?.server === "bundled" ? servers.asr?.state === "ready" && models.base_url === servers.asr.base_url &&
            models.server_generation === servers.asr.generation : models.base_url === settings?.base_url);
    const knownModels = modelsCurrent ? models.models ?? [] : [];
    const selectedModel = knownModels.find(row => row.id === draft?.model);
    const dirty = JSON.stringify(draft) !== JSON.stringify(settings);
    const updateSource = (source, values) => setDraft(previous => ({ ...previous, [source]: { ...previous[source], ...values } }));
    return <section className={styles.container} aria-label={t("realtime.title")}>
        <h3>{t("realtime.title")}</h3>
        <p>{t("realtime.scope")}</p>
        <p>{t("realtime.server_help")}</p>
        {draft && <form onSubmit={event => { event.preventDefault(); send("/set/data/realtime_asr_settings", draft); }}>
            <label>{t("speech_servers.asr_selection")}<select aria-label={t("speech_servers.asr_selection")} value={draft.server || "external"}
                onChange={event => setDraft({ ...draft, server: event.target.value })}>
                {["external", "bundled"].map(value => <option key={value} value={value}>{t(`speech_servers.${value}`)}</option>)}
            </select></label>
            {draft.server !== "bundled" && <label>{t("realtime.url")}<input aria-label={t("realtime.url")} value={draft.base_url}
                onChange={event => setDraft({ ...draft, base_url: event.target.value })} /></label>}
            <label>{t("realtime.model")}<select aria-label={t("realtime.model")} value={draft.model}
                onChange={event => setDraft({ ...draft, model: event.target.value })}>
                <option value="">{t("realtime.select_model")}</option>
                {draft.model && !selectedModel && <option value={draft.model}>{draft.model} ({t("realtime.unavailable")})</option>}
                {knownModels.map(row => <option key={row.id} value={row.id}>{row.id}</option>)}
            </select></label>
            <button type="button" onClick={() => send("/get/data/realtime_asr_models")}>{t("realtime.refresh_models")}</button>
            <p>{t("realtime.auto_help")}</p>
            {models.error_code && <p role="alert">{models.error_code}</p>}
            <button type="button" onClick={refreshDevices}>{t("realtime.refresh_devices")}</button>
            {["mic", "speaker"].map(source => {
                const choices = endpoints[source]?.endpoints ?? [];
                const follow = !draft[source].endpoint && draft[source].follow_default !== false;
                const selected = follow || choices.find(row => key(row.endpoint) === key(draft[source].endpoint));
                // "auto" only for a model that detects the language (Qwen3-ASR).
                const languages = [...(selectedModel?.detects_language ? ["auto"] : []), ...(selectedModel?.languages ?? [])];
                const owner = state[source];
                const failure = endpoints[source]?.error_code || owner?.error_code;
                return <fieldset key={source}>
                    <legend>{t(`realtime.${source}`)}</legend>
                    {source === "speaker" && <p>{t("realtime.speaker_help")}</p>}
                    <label>{t(`realtime.${source}_input`)}<select aria-label={t(`realtime.${source}_input`)} value={follow ? FOLLOW : key(draft[source].endpoint)}
                        onChange={event => updateSource(source, event.target.value === FOLLOW ? { endpoint: null, follow_default: true }
                            : { endpoint: choices.find(row => key(row.endpoint) === event.target.value)?.endpoint ?? null, follow_default: false })}>
                        <option value="">{t("realtime.select_device")}</option>
                        <option value={FOLLOW}>{t(`realtime.follow_default_${source}`)}</option>
                        {draft[source].endpoint && !selected && <option value={key(draft[source].endpoint)}>{t("realtime.disconnected")}</option>}
                        {choices.map(row => <option key={key(row.endpoint)} value={key(row.endpoint)}>{row.label}</option>)}
                    </select></label>
                    <label>{t(`realtime.${source}_language`)}<select aria-label={t(`realtime.${source}_language`)} value={draft[source].language}
                        onChange={event => updateSource(source, { language: event.target.value })}>
                        {!languages.includes(draft[source].language) && <option value={draft[source].language}>{draft[source].language}</option>}
                        {languages.map(language => <option key={language} value={language}>{language === "auto" ? t("realtime.auto_language") : language}</option>)}
                    </select></label>
                    {follow && <p>{t("realtime.follow_default_help")}</p>}
                    <button type="button" disabled={dirty || !selected || !selectedModel || !languages.includes(draft[source].language) ||
                        !owner || owner.requested || !!endpoints[source]?.error_code}
                        onClick={() => send("/run/start_realtime_asr", { source })}>{t(`realtime.start_${source}`)}</button>
                    <button type="button" onClick={() => send("/run/stop_realtime_asr", { source })}>{t(`realtime.stop_${source}`)}</button>
                    <p role="status">{t(`realtime.state_${owner?.state ?? "unknown"}`)}</p>
                    {failure && <p role="alert">{failure}</p>}
                </fieldset>;
            })}
            <p>{t("realtime.save_help")}</p>
            <button type="submit" disabled={!dirty}>{t("realtime.save")}</button>
        </form>}
        {error && <p role="alert">{error}</p>}
    </section>;
};
