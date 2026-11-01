import { useEffect, useMemo } from "react";
import { useSettingsDraft } from "../../../../../../logics/voice/useSettingsDraft";
import { VoiceRouteSummary, VoiceRouteControls } from "../device/VoiceRouteSettings";
import { SectionLabelComponent } from "../_components/section_label_component/SectionLabelComponent";
import styles from "./VoiceSettings.module.scss";
import { useI18n } from "@useI18n";
import { useVoice, sourceKey as key } from "../../../../../../logics/voice/useVoice";
import { ModelDownloads } from "./ModelDownloads";
import { StatusLine } from "./StatusLine";
import { EnvReadout } from "../_components/env_readout/EnvReadout";

const defaults = { mode: "passthrough", runtime: "", reference: "", engine: "seed-vc",
    rvc_runtime: "", rvc_model: "", rvc_index: "", rvc_pitch: 0, rvc_index_rate: 0 };

export const DirectVoiceSettings = ({ variant = "all" }) => {
    const { t } = useI18n();
    const { settings, route, error, directState, directOwner, directPending, directSources, directError, updateDirectError, send, setDirectDraftBlocked,
        selectedSource: selected, setSelectedSource: setSelected } = useVoice();
    const saved = useMemo(() => {
        if (!directState.settings) return null;
        const value = { ...defaults, ...directState.settings };
        if (variant === "rvc") return { ...value, mode: "converted", engine: "rvc" };
        if (variant === "legacy" && value.engine === "rvc") return { ...value, mode: "passthrough", engine: "seed-vc" };
        return value;
    }, [directState.settings, variant]);
    const busy = !!directPending || directState.requested || directState.pending || directState.stopping;
    const validNumbers = draft => Number.isInteger(draft.rvc_pitch) && Math.abs(draft.rvc_pitch) <= 24 &&
        Number.isFinite(draft.rvc_index_rate) && draft.rvc_index_rate >= 0 && draft.rvc_index_rate <= 1;
    // The RVC page edits converted RVC; selecting it is itself a change to save.
    const needsSelection = draft => draft.mode !== directState.settings?.mode || draft.engine !== directState.settings?.engine;
    const label = ([name]) => t(name === "mode" ? "voice.direct_mode" : name === "engine" ? "voice.vc_engine" : `voice.vc_${name}`, { defaultValue: name });
    const form = useSettingsDraft(saved, directError, updateDirectError, { label,
        write: value => send("/set/data/direct_voice_settings", value), canSave: draft => !busy && validNumbers(draft),
        pending: draft => needsSelection(draft) && JSON.stringify(draft) === JSON.stringify(saved) ? [t(variant === "rvc" ? "voice.vc_engine" : "voice.direct_mode")] : [] });
    const { draft, setDraft, saving, dirty } = form;
    useEffect(() => {
        setDirectDraftBlocked(dirty || saving);
        return () => setDirectDraftBlocked(false);
    }, [dirty, saving, setDirectDraftBlocked]);
    useEffect(() => {
        send("/get/data/voice_settings");
        send("/get/data/direct_voice_sources");
        send("/get/data/direct_voice_state");
    }, [send]);
    if (!draft) return <p role="status">{t("voice.input_unknown")}</p>;
    const isRvc = directOwner === "rvc";
    const ownsInput = !!directOwner && (variant === "all" || (variant === "rvc" ? isRvc : !isRvc));
    const sources = directSources.sources || [];
    const source = sources.find(item => key(item.id) === selected);
    const managed = settings?.routing === "managed";
    const unavailable = directSources.error || directError || directState.error;
    const converted = draft.mode === "converted";
    const rvc = draft.engine === "rvc";
    const complete = !converted || (rvc ? (draft.rvc_runtime.trim() && /\.pth$/i.test(draft.rvc_model) &&
        (!draft.rvc_index || /\.index$/i.test(draft.rvc_index)) &&
        (!draft.rvc_index_rate || draft.rvc_index) && validNumbers(draft)) : (draft.runtime.trim() && draft.reference.trim()));
    const options = rvc ? { engine: "rvc", runtime: draft.rvc_runtime, model: draft.rvc_model,
        index: draft.rvc_index, pitch: draft.rvc_pitch, index_rate: draft.rvc_index_rate } :
        { runtime: draft.runtime, reference: draft.reference };
    let status = "voice.input_stopped";
    if (!directState.observation_id) status = "voice.input_unknown";
    else if (directState.error) status = "voice.input_failed";
    else if (directPending || directState.pending || directState.stopping) status = "voice.input_pending";
    else if (directState.active) status = directState.mode !== "converted" ? "voice.input_active" :
        directState.conversion_state === "idle" ? "voice.vc_idle" :
            directState.conversion_verified ? "voice.vc_active" : "voice.vc_ready";
    const tone = status === "voice.input_failed" ? "failed" : status === "voice.input_pending" ? "pending" :
        ["voice.input_active", "voice.vc_idle", "voice.vc_active", "voice.vc_ready"].includes(status) ? "active" : "idle";
    return <section className={styles.container} aria-label={variant === "rvc" ? "RVC" : t("voice.input_title")} data-setting-id={variant === "rvc" ? "rvc_settings" : "direct_voice_settings"}>
        <SectionLabelComponent label={variant === "rvc" ? "RVC" : t("voice.input_title")} />
        <StatusLine tone={tone}>{t(status)}</StatusLine>
        <VoiceRouteSummary />
        <p>{t(variant === "rvc" ? "voice.vc_rvc_hint" : "voice.input_description")}</p>
        {busy && !ownsInput && <p role="alert">{t("voice_ui.input_conflict")}</p>}
        <fieldset className={styles.fields} disabled={saving}>
        {variant !== "rvc" && <label>{t("voice.direct_mode")}
            <select aria-label={t("voice.direct_mode")} value={draft.mode} disabled={busy} onChange={e => setDraft({ ...draft, mode: e.target.value })}>
                <option value="passthrough">{t("voice.direct_passthrough")}</option>
                <option value="converted">{t("voice.direct_converted")}</option>
            </select>
        </label>}
        {converted && <>
            {variant === "all" && <label>{t("voice.vc_engine")}
                <select aria-label={t("voice.vc_engine")} value={draft.engine} disabled={busy} onChange={e => setDraft({ ...draft, engine: e.target.value })}>
                    <option value="seed-vc">Seed-VC</option>
                    <option value="rvc">RVC</option>
                </select>
            </label>}
            {/* The RVC page already opens with the RVC hint. */}
            {variant !== "rvc" && <p>{t(rvc ? "voice.vc_rvc_hint" : "voice.vc_hint")}</p>}
            {(rvc ? ["rvc_runtime", "rvc_model", "rvc_index"] : ["runtime", "reference"]).map(name => <label key={name}>{t(`voice.vc_${name}`)}
                <input type="text" value={draft[name]} disabled={busy} maxLength={4096}
                    onChange={e => setDraft({ ...draft, [name]: e.target.value })} />
            </label>)}
            {rvc && [["rvc_pitch", -24, 24, 1], ["rvc_index_rate", 0, 1, 0.05]].map(([name, min, max, step]) =>
                <label key={name}>{t(`voice.vc_${name}`)}
                    <input type="number" min={min} max={max} step={step} disabled={busy}
                        aria-invalid={name === "rvc_pitch" ? !Number.isInteger(draft[name]) || Math.abs(draft[name]) > 24 :
                            !Number.isFinite(draft[name]) || draft[name] < 0 || draft[name] > 1}
                        value={Number.isFinite(draft[name]) ? draft[name] : ""}
                        onChange={e => setDraft({ ...draft, [name]: e.target.valueAsNumber })} />
                </label>)}
            {rvc && !validNumbers(draft) && <p role="alert">{t("voice_ui.invalid_rvc_numbers")}</p>}
            {rvc && draft.rvc_index_rate > 0 && !draft.rvc_index && <p role="alert">{t("voice_ui.rvc_index_required")}</p>}
        </>}
        </fieldset>
        {/* Other unsaved edits survive an apply; only edited model or index paths conflict. */}
        {rvc && <ModelDownloads targets={["rvc"]} blocked={busy || saving ? "busy" :
            draft.rvc_model !== saved.rvc_model || draft.rvc_index !== saved.rvc_index ? "edited" : false}
            expected={{ rvc: { model: directState.settings?.rvc_model || "", index: directState.settings?.rvc_index || "" } }} />}
        {form.navigationDialog}
        <label>{t("voice.input_source")}
            <select aria-label={t("voice.input_source")} value={selected} disabled={busy} onChange={e => setSelected(e.target.value)}>
                <option value="">{t("voice.select_input")}</option>
                {selected && !source && <option value={selected}>{t("voice.disconnected")}</option>}
                {sources.map(item => <option key={key(item.id)} value={key(item.id)}>{item.label}</option>)}
            </select>
        </label>
        <button type="button" onClick={() => send("/get/data/direct_voice_sources")}>{t("voice.refresh_inputs")}</button>
        <p>{t("voice.input_selection_hint")}</p>
        {!managed && <><p>{t("voice.input_requires_managed")}</p>
            <button type="button" disabled={!settings || busy || saving}
                onClick={() => send("/set/data/voice_settings", { ...settings, routing: "managed" })}>{t("voice.prepare_microphone")}</button>
            {error && <p role="alert">{t(`voice_setup_errors.${error}`, { defaultValue: error })}</p>}
        </>}
        {managed && <VoiceRouteControls />}
        <button type="button" disabled={!managed || !route.ready || route.pending || !source || !!directSources.error || !complete || dirty || saving ||
            !directState.observation_id || busy || needsSelection(draft)}
            onClick={() => send("/run/start_direct_voice", converted ? {
                source: source.id, mode: "converted", options,
            } : { source: source.id })}>{t("voice.input_start")}</button>
        <button type="button" disabled={!ownsInput || !busy} onClick={() => send("/run/stop_direct_voice")}>{t("voice.input_stop")}</button>
        {/* The TTS monitor setting also covers converted voice; it is fixed at Start. */}
        <p>{t(!converted ? "voice.vc_monitor_passthrough" : settings?.monitor === "on" ? "voice.vc_monitor_on" : "voice.vc_monitor_off")}</p>
        {directState.monitor_error && <EnvReadout tone="failed"><p>{t(`voice.monitor_errors.${directState.monitor_error}`, { defaultValue: t("voice.monitor_error") })}</p></EnvReadout>}
        <p>{t("voice.input_scope")}</p>
        {unavailable && <p role="alert">{t("voice.input_error")}: {unavailable}</p>}
    </section>;
};
