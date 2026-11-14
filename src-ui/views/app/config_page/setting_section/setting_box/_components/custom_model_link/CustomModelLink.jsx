import { useState } from "react";
import { useI18n } from "@useI18n";
import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import { generateLocalizedDocumentUrl } from "@ui_configs";

// Opens the user guide's section on bringing your own model (a file you trained, downloaded
// elsewhere or bought) for this setting, in the browser, in the display language. It only
// opens the page: no setting, model or audio changes.
// section: the heading's anchor on the page, the same in both languages (tts, asr,
// whisper-server, rvc, seed-vc, translation).
export const CustomModelLink = ({ section }) => {
    const { t, i18n } = useI18n();
    const [failed, setFailed] = useState(false);
    const url = `${generateLocalizedDocumentUrl(i18n.language).vrct_document_custom_models_url}#${section}`;
    const open = async event => {
        if (!isTauri()) return;
        event.preventDefault();
        try { await openUrl(url); setFailed(false); }
        catch { setFailed(true); }
    };
    return <p>
        <a href={url} onClick={open} target="_blank" rel="noreferrer">{t("config_page.custom_model_link")}</a>
        {failed && <span role="alert"><span>{t("model_downloads.link_error")}</span> <code style={{ overflowWrap: "anywhere" }}>{url}</code></span>}
    </p>;
};
