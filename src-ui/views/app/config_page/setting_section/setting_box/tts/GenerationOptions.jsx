import { useEffect } from "react";
import { useI18n } from "@useI18n";
import { useVoice } from "../../../../../../logics/voice/useVoice";
import { useSpeechServers } from "../../../../../../logics/voice/useSpeechServers";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import { FormRow } from "../_components/form_row/FormRow";

export const validGenerationOptions = draft => ["japanese", "multilingual"].every(role => {
    const seed = draft[`${role}_seed`] || "", instruction = draft[`${role}_instructions`] || "";
    return (!seed || (/^[0-9]{1,16}$/.test(seed) && BigInt(seed) <= 9007199254740991n)) &&
        Array.from(instruction).length <= 4000 && !/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(instruction);
});

export const GenerationOptions = ({ role, draft, field }) => {
    const { t } = useI18n();
    const { settings, modelOptions, send } = useVoice();
    const { state } = useSpeechServers();
    const server = settings?.[`${role}_server`], url = settings?.[`${role}_url`];
    const owner = state[role];
    const generation = owner?.generation, phase = owner?.state;
    const canQuery = server === "bundled" ? phase === "ready" : !!url;
    useEffect(() => {
        if (!canQuery) return;
        const query = () => send("/get/data/tts_model_options", { role });
        query();
        const timer = setInterval(query, 10000);
        return () => clearInterval(timer);
    }, [role, server, url, generation, phase, canQuery, send]);
    const row = modelOptions[role];
    const matches = canQuery && row?.server === server && row.configured_url === url &&
        (server !== "bundled" || (row.server_generation === generation && row.base_url === owner?.base_url)) &&
        draft[`${role}_server`] === server && draft[`${role}_url`] === url;
    const options = matches ? row.options : null;
    const seedKey = `${role}_seed`, instructionKey = `${role}_instructions`;
    const seed = draft[seedKey] || "", instructions = draft[instructionKey] || "";
    const fixed = seed !== "";
    const support = value => t(`voice_ui.${!options ? "not_confirmed" : value ? "supported" : "not_supported"}`);
    return <>
        <label>{t("voice_ui.seed_mode")}<select aria-label={t("voice_ui.seed_mode")} value={fixed ? "fixed" : "random"}
            onChange={e => field(seedKey, e.target.value === "fixed" ? "0" : "")}>
            <option value="random">{t("voice_ui.seed_random")}</option><option value="fixed">{t("voice_ui.seed_fixed")}</option>
        </select></label>
        {fixed && <label>{t("voice_ui.seed_value")}<input type="text" inputMode="numeric" value={seed}
            aria-invalid={!/^[0-9]{1,16}$/.test(seed) || BigInt(/^[0-9]{1,16}$/.test(seed) ? seed : "0") > 9007199254740991n}
            onChange={e => field(seedKey, e.target.value)} /></label>}
        <FormRow label={t("voice_ui.instruction")} description={t("voice_ui.instruction_hint", { count: Array.from(instructions).length })} fold={false}>
            <textarea aria-label={t("voice_ui.instruction")} value={instructions} maxLength={8000} rows={3}
                onChange={e => field(instructionKey, e.target.value)} />
        </FormRow>
        <EnvReadout><p>{t("voice_ui.option_support", { seed: support(options?.seed), instruction: support(options?.instructions) })}{options?.model ? ` · ${options.model}` : ""}</p></EnvReadout>
        {(fixed || instructions.trim()) && (!options || (fixed && !options.seed) || (instructions.trim() && !options.instructions)) &&
            <p>{t("voice_ui.options_warning")}</p>}
        {options?.seed && fixed && /^[0-9]{1,16}$/.test(seed) &&
            (BigInt(seed) < BigInt(options.seed.minimum) || BigInt(seed) > BigInt(options.seed.maximum)) && <p role="alert">{t("voice_ui.seed_range", options.seed)}</p>}
        <button type="button" disabled={!canQuery} onClick={() => send("/get/data/tts_model_options", { role })}>{t("voice_ui.check_options")}</button>
    </>;
};
