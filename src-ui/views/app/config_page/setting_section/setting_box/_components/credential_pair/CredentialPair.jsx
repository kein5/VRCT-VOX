import { useMemo, useState } from "react";
import { useI18n } from "@useI18n";
import { useStdoutToPython } from "@useStdoutToPython";
import { useSettingsDraft } from "../../../../../../../logics/voice/useSettingsDraft";
import { endpointDescription } from "../../../../../../../logics/common/endpointPrivacy";
import { AuthKeyContainer, EntryWithSaveButtonContainer } from "../../_templates/Templates";

export const CredentialPair = ({ settings, base, provider, section }) => {
    const { t } = useI18n();
    const { asyncStdoutToPython } = useStdoutToPython();
    const [error, updateError] = useState(null);
    const url = settings[`current${base}URL`], key = settings[`current${base}AuthKey`];
    const saved = useMemo(() => ({ url: url.data ?? "", auth_key: key.data ?? "" }), [url.data, key.data]);
    const label = field => t(`config_page.${section}.${provider}_${field}.label`);
    const write = async value => {
        const urlChanged = value.url !== saved.url, keyChanged = value.auth_key !== saved.auth_key;
        let endpoint, data;
        if (urlChanged && keyChanged) {
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
        const canonical = urlChanged && keyChanged ? response.result : {
            ...saved, [urlChanged ? "url" : "auth_key"]: response.result,
        };
        return { ...response, result: { ...canonical, auth_key: canonical.auth_key ?? "" } };
    };
    const ready = url.state !== "pending" && key.state !== "pending";
    const form = useSettingsDraft(saved, error, updateError, { write, canSave: ready, label: ([field]) => label(field) });
    if (!form.draft) return null;
    const field = name => ({
        label: label(name), variable: form.draft[name], state: form.saving || !ready ? "pending" : "ok",
        onChangeFunction: value => form.setDraft(previous => ({ ...previous, [name]: value })),
        saveFunction: () => { if (ready && form.dirty) return form.submit(write); },
        remove_border_bottom: true,
    });
    return <>
        <EntryWithSaveButtonContainer {...field("url")} width="24rem"
            desc={endpointDescription(form.draft.url, t(`config_page.${section}.${provider}_url.desc`), t)} />
        <AuthKeyContainer {...field("auth_key")}
            desc={section === "transcription" ? t(`config_page.${section}.${provider}_auth_key.desc`) : undefined} />
        {form.navigationDialog}
    </>;
};
