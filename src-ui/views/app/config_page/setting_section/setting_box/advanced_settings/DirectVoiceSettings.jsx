import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useVoice } from "../../../../../../logics/voice/useVoice";

// Keep the complete backend identity. Refresh never rebinds a selected name.
const key = id => JSON.stringify([id.cookie, id.serial, id.name, id.media_class]);
const defaults = { mode: "passthrough", runtime: "", reference: "", engine: "seed-vc",
    rvc_runtime: "", rvc_model: "", rvc_index: "", rvc_pitch: 0, rvc_index_rate: 0 };

export const DirectVoiceSettings = () => {
    const { t } = useI18n();
    const { settings, directState, directSources, directError, send } = useVoice();
    const [selected, setSelected] = useState("");
    const [draft, setDraft] = useState(defaults);
    const [saving, setSaving] = useState(false);
    const savedKey = JSON.stringify({ ...defaults, ...directState.settings });
    useEffect(() => {
        setDraft(JSON.parse(savedKey));
        setSaving(false);
    }, [savedKey]);
    useEffect(() => { if (directError) setSaving(false); }, [directError]);
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
    const busy = directState.requested || directState.pending;
    const dirty = JSON.stringify(draft) !== savedKey;
    const converted = draft.mode === "converted";
    const rvc = draft.engine === "rvc";
    const validNumbers = Number.isInteger(draft.rvc_pitch) && Math.abs(draft.rvc_pitch) <= 24 &&
        Number.isFinite(draft.rvc_index_rate) && draft.rvc_index_rate >= 0 && draft.rvc_index_rate <= 1;
    const complete = !converted || (rvc ? (draft.rvc_runtime.trim() && /\.pth$/i.test(draft.rvc_model) &&
        (!draft.rvc_index || /\.index$/i.test(draft.rvc_index)) &&
        (!draft.rvc_index_rate || draft.rvc_index) && validNumbers) : (draft.runtime.trim() && draft.reference.trim()));
    const options = rvc ? { engine: "rvc", runtime: draft.rvc_runtime, model: draft.rvc_model,
        index: draft.rvc_index, pitch: draft.rvc_pitch, index_rate: draft.rvc_index_rate } :
        { runtime: draft.runtime, reference: draft.reference };
    let status = "voice.input_stopped";
    if (!directState.observation_id) status = "voice.input_unknown";
    else if (directState.error) status = "voice.input_failed";
    else if (directState.pending) status = directState.mode === "converted" ? "voice.vc_preparing" : "voice.input_pending";
    else if (directState.active) status = directState.mode !== "converted" ? "voice.input_active" :
        directState.conversion_state === "idle" ? "voice.vc_idle" :
            directState.conversion_verified ? "voice.vc_active" : "voice.vc_ready";
    return <section aria-label={t("voice.input_title")}>
        <h3>{t("voice.input_title")}</h3>
        <p>{t("voice.input_description")}</p>
        <label>{t("voice.direct_mode")}
            <select value={draft.mode} disabled={busy} onChange={e => setDraft({ ...draft, mode: e.target.value })}>
                <option value="passthrough">{t("voice.direct_passthrough")}</option>
                <option value="converted">{t("voice.direct_converted")}</option>
            </select>
        </label>
        {converted && <>
            <label>{t("voice.vc_engine")}
                <select value={draft.engine} disabled={busy} onChange={e => setDraft({ ...draft, engine: e.target.value })}>
                    <option value="seed-vc">Seed-VC</option>
                    <option value="rvc">RVC</option>
                </select>
            </label>
            <p>{t(rvc ? "voice.vc_rvc_hint" : "voice.vc_hint")}</p>
            {(rvc ? ["rvc_runtime", "rvc_model", "rvc_index"] : ["runtime", "reference"]).map(name => <label key={name}>{t(`voice.vc_${name}`)}
                <input type="text" value={draft[name]} disabled={busy} maxLength={4096}
                    onChange={e => setDraft({ ...draft, [name]: e.target.value })} />
            </label>)}
            {rvc && [["rvc_pitch", -24, 24, 1], ["rvc_index_rate", 0, 1, 0.05]].map(([name, min, max, step]) =>
                <label key={name}>{t(`voice.vc_${name}`)}
                    <input type="number" min={min} max={max} step={step} disabled={busy}
                        value={Number.isFinite(draft[name]) ? draft[name] : ""}
                        onChange={e => setDraft({ ...draft, [name]: e.target.valueAsNumber })} />
                </label>)}
        </>}
        <button type="button" disabled={busy || !dirty || saving || !validNumbers} onClick={() => {
            setSaving(true);
            send("/set/data/direct_voice_settings", draft);
        }}>{t(saving ? "voice.saving" : "voice.direct_save")}</button>
        <label>{t("voice.input_source")}
            <select value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}>
                <option value="">{t("voice.select_input")}</option>
                {selected && !source && <option value={selected}>{t("voice.disconnected")}</option>}
                {sources.map(item => <option key={key(item.id)} value={key(item.id)}>{item.label}</option>)}
            </select>
        </label>
        <button type="button" onClick={() => send("/get/data/direct_voice_sources")}>{t("voice.refresh_inputs")}</button>
        {!managed && <p>{t("voice.input_requires_managed")}</p>}
        <button type="button" disabled={!managed || !source || !!directSources.error || !complete || dirty || saving ||
            !directState.observation_id || busy}
            onClick={() => send("/run/start_direct_voice", converted ? {
                source: source.id, mode: "converted", options,
            } : { source: source.id })}>{t("voice.input_start")}</button>
        <button type="button" onClick={() => send("/run/stop_direct_voice")}>{t("voice.input_stop")}</button>
        <p role="status">{t(status)}</p>
        <p>{t("voice.input_scope")}</p>
        {unavailable && <p role="alert">{t("voice.input_error")}: {unavailable}</p>}
    </section>;
};
