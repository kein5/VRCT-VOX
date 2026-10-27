import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useVoice } from "../../../../../../logics/voice/useVoice";

// Keep the complete backend identity. Refresh never rebinds a selected name.
const key = id => JSON.stringify([id.cookie, id.serial, id.name, id.media_class]);

export const DirectVoiceSettings = () => {
    const { t } = useI18n();
    const { settings, directState, directSources, directError, send } = useVoice();
    const [selected, setSelected] = useState("");
    useEffect(() => {
        send("/get/data/direct_voice_sources");
        send("/get/data/direct_voice_state");
        const timer = setInterval(() => send("/get/data/direct_voice_state"), 1000);
        return () => clearInterval(timer);
    }, [send]);
    const sources = directSources.sources || [];
    const source = sources.find(item => key(item.id) === selected);
    const managed = settings?.routing === "managed";
    const unavailable = directSources.error || directError || directState.error;
    return <section aria-label={t("voice.input_title")}>
        <h3>{t("voice.input_title")}</h3>
        <p>{t("voice.input_description")}</p>
        <label>{t("voice.input_source")}
            <select value={selected} disabled={directState.requested}
                onChange={e => setSelected(e.target.value)}>
                <option value="">{t("voice.select_input")}</option>
                {selected && !source && <option value={selected}>{t("voice.disconnected")}</option>}
                {sources.map(item => <option key={key(item.id)} value={key(item.id)}>{item.label}</option>)}
            </select>
        </label>
        <button type="button" onClick={() => send("/get/data/direct_voice_sources")}>{t("voice.refresh_inputs")}</button>
        {!managed && <p>{t("voice.input_requires_managed")}</p>}
        <button type="button" disabled={!managed || !source || !!directSources.error ||
            !directState.observation_id || directState.requested || directState.pending}
            onClick={() => send("/run/start_direct_voice", { source: source.id })}>{t("voice.input_start")}</button>
        <button type="button" onClick={() => send("/run/stop_direct_voice")}>{t("voice.input_stop")}</button>
        <p role="status">{t(!directState.observation_id ? "voice.input_unknown" : directState.error ? "voice.input_failed" :
            directState.pending ? "voice.input_pending" : directState.active ? "voice.input_active" : "voice.input_stopped")}</p>
        <p>{t("voice.input_scope")}</p>
        {unavailable && <p role="alert">{t("voice.input_error")}: {unavailable}</p>}
    </section>;
};
