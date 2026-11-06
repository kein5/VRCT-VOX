import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { useStdoutToPython } from "@useStdoutToPython";
import { useSettingsDraft } from "../../../../../../../logics/voice/useSettingsDraft";
import { endpointDescription } from "../../../../../../../logics/common/endpointPrivacy";
import { AuthKeyContainer, EntryWithSaveButtonContainer } from "../../_templates/Templates";

export const CredentialPair = ({ settings, base, provider, section }) => {
    const { t } = useI18n();
    const { asyncStdoutToPython } = useStdoutToPython();
    const [error, updateError] = useState(null);
    // Explicit input may equal the saved key; equality alone cannot prove reentry.
    const enteredKey = useRef(null);
    const url = settings[`current${base}URL`], key = settings[`current${base}AuthKey`];
    const saved = useMemo(() => ({ url: url.data ?? "", auth_key: key.data ?? "" }), [url.data, key.data]);
    const label = field => t(`config_page.${section}.${provider}_${field}.label`);
    const ready = url.state !== "pending" && key.state !== "pending";
    const requiresKey = value => !!saved.auth_key && value.url.trim() !== saved.url.trim() && !value.auth_key.trim();
    const canSave = value => ready && !requiresKey(value);
    const write = async value => {
        if (!canSave(value)) return false;
        const submittedKey = enteredKey.current;
        const urlChanged = value.url.trim() !== saved.url.trim(), keyChanged = value.auth_key !== saved.auth_key;
        const pairChanged = urlChanged && (keyChanged || !!value.auth_key);
        let endpoint, data;
        if (pairChanged) {
            endpoint = `/set/data/${provider}_auth_key_and_url`;
            data = value;
        } else if (urlChanged) {
            endpoint = `/set/data/${provider}_url`;
            data = value.url;
        } else {
            endpoint = `/${value.auth_key ? "set" : "delete"}/data/${provider}_auth_key`;
            data = value.auth_key || undefined;
        }
        const response = await asyncStdoutToPython(endpoint, data);
        if (response?.status !== 200) {
            updateError(response?.result?.error_code || "save_unconfirmed");
            return response;
        }
        if (enteredKey.current === submittedKey) enteredKey.current = null;
        const canonical = pairChanged ? response.result : {
            ...saved, [urlChanged ? "url" : "auth_key"]: response.result,
        };
        return { ...response, result: { ...canonical, auth_key: canonical.auth_key ?? "" } };
    };
    const form = useSettingsDraft(saved, error, updateError, { write, canSave, label: ([field]) => label(field) });
    useEffect(() => {
        // Discard (including the leave dialog) restores this exact saved object.
        if (form.draft === saved) enteredKey.current = null;
    }, [form.draft, saved]);
    if (!form.draft) return null;
    const field = name => ({
        label: label(name), variable: form.draft[name], state: form.saving || !ready ? "pending" : "ok",
        onChangeFunction: value => {
            if (name === "auth_key") enteredKey.current = value.trim() ? {} : null;
            const restoreKey = name === "url" && saved.auth_key && !enteredKey.current;
            form.setDraft(previous => ({ ...previous, [name]: value,
                ...(restoreKey
                    ? { auth_key: value.trim() === saved.url.trim() ? saved.auth_key : "" } : {}),
            }));
        },
        saveFunction: () => { if (canSave(form.draft) && form.dirty) return form.submit(write); },
        remove_border_bottom: true,
    });
    return <>
        <EntryWithSaveButtonContainer {...field("url")} width="24rem"
            desc={endpointDescription(form.draft.url, t(`config_page.${section}.${provider}_url.desc`), t)} />
        <AuthKeyContainer {...field("auth_key")}
            add_warnings={requiresKey(form.draft) ? [{ label: t("config_page.common.credential_reentry_required") }] : []}
            desc={section === "transcription" ? t(`config_page.${section}.${provider}_auth_key.desc`) : undefined} />
        {form.navigationDialog}
    </>;
};
