import { useEffect, useRef, useState } from "react";
import { useI18n } from "@useI18n";

// A write is confirmed only when the backend returns the submitted values.
export function useSettingsDraft(saved, error, updateError) {
    const { t } = useI18n();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const submitted = useRef(null);
    const savedKey = JSON.stringify(saved);
    const dirty = draft !== null && JSON.stringify(draft) !== savedKey;
    const current = useRef({ draft, dirty });
    current.current = { draft, dirty };
    useEffect(() => {
        if (saved == null) return;
        const acknowledged = submitted.current !== null && savedKey === submitted.current;
        if (current.current.draft === null || !current.current.dirty || acknowledged) setDraft(saved);
        if (acknowledged) { setSaving(false); submitted.current = null; }
    }, [savedKey, saved]);
    useEffect(() => { if (error) { setSaving(false); submitted.current = null; } }, [error]);
    useEffect(() => {
        if (!saving) return;
        const timer = setTimeout(() => { setSaving(false); submitted.current = null; updateError("save_unconfirmed"); }, 5000);
        return () => clearTimeout(timer);
    }, [saving, updateError]);
    const [leaving, setLeaving] = useState(null);
    const dialog = useRef(null);
    useEffect(() => {
        if (!dirty && !saving) return;
        const guard = event => {
            if (event.defaultPrevented) return;
            event.preventDefault();
            setLeaving(() => event.detail.proceed);
        };
        const unload = event => { event.preventDefault(); event.returnValue = ""; };
        window.addEventListener("vrct:settings-leave", guard);
        window.addEventListener("beforeunload", unload);
        return () => {
            window.removeEventListener("vrct:settings-leave", guard);
            window.removeEventListener("beforeunload", unload);
        };
    }, [dirty, saving]);
    useEffect(() => { if (leaving) dialog.current?.showModal(); }, [leaving]);
    const discard = () => { setDraft(saved); setSaving(false); submitted.current = null; updateError(null); };
    return {
        draft, setDraft, dirty, saving, discard,
        submit: write => { updateError(null); submitted.current = JSON.stringify(draft); setSaving(true); write(draft); },
        saveState: error ? "save_failed" : saving ? "saving" : dirty ? "unsaved" : "saved",
        navigationDialog: leaving && <dialog ref={dialog} onCancel={() => setLeaving(null)} aria-label={t("voice_ui.leave_title")}>
            <p>{t("voice_ui.leave_hint")}</p>
            <button type="button" autoFocus onClick={() => setLeaving(null)}>{t("voice_ui.keep_editing")}</button>
            <button type="button" onClick={() => { const proceed = leaving; discard(); setLeaving(null); proceed(); }}>{t("voice_ui.discard_leave")}</button>
        </dialog>,
    };
}
