import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { rebaseDraft } from "./draftRebase";
import { changedPaths, setSaveBarEntry } from "./saveBar";

// A write is confirmed only when the backend returns the submitted values.
// `write` sends a draft; with it the form is saved from the config page top
// bar, which lists the changed fields by `label(path)`. `canSave` may be a
// function of the draft. `pending` (a list, or a function of the draft) names
// changes that are not in the draft,
// e.g. an engine the backend has not selected yet.
export function useSettingsDraft(saved, error, updateError, { write, canSave = true, label = path => path.join("."), pending = [] } = {}) {
    const { t } = useI18n();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const submitted = useRef(null);
    const savedKey = JSON.stringify(saved);
    const previousSavedKey = useRef(savedKey);
    const dirty = draft !== null && JSON.stringify(draft) !== savedKey;
    const current = useRef({ draft, dirty });
    current.current = { draft, dirty };
    useEffect(() => {
        if (saved == null) return;
        const acknowledged = submitted.current !== null && savedKey === submitted.current;
        if (current.current.draft === null || acknowledged) setDraft(saved);
        else setDraft(rebaseDraft(JSON.parse(previousSavedKey.current), current.current.draft, saved));
        previousSavedKey.current = savedKey;
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
    const submit = send => { updateError(null); submitted.current = JSON.stringify(draft); setSaving(true); send(draft); };
    const saveState = error ? "save_failed" : saving ? "saving" : dirty ? "unsaved" : "saved";
    const id = useId();
    const changes = draft === null ? [] : [...changedPaths(saved, draft).map(label), ...(typeof pending === "function" ? pending(draft) : pending)];
    const entry = { dirty: changes.length > 0, saving, saveState, changes, canSave: !!write && draft !== null && !!(typeof canSave === "function" ? canSave(draft) : canSave),
        save: () => submit(write), discard };
    const entryRef = useRef(entry);
    entryRef.current = entry;
    const entryKey = JSON.stringify([entry.dirty, saving, saveState, changes, entry.canSave]);
    useEffect(() => {
        if (!write) return;
        // Callbacks read the latest render, so only visible state republishes.
        setSaveBarEntry(id, { ...entryRef.current, save: () => entryRef.current.save(), discard: () => entryRef.current.discard() });
    }, [id, entryKey, !write]);
    useEffect(() => () => setSaveBarEntry(id, null), [id]);
    return {
        draft, setDraft, dirty, saving, discard, submit, saveState,
        navigationDialog: leaving && <dialog ref={dialog} onCancel={() => setLeaving(null)} aria-label={t("voice_ui.leave_title")}>
            <p>{t("voice_ui.leave_hint")}</p>
            <button type="button" autoFocus onClick={() => setLeaving(null)}>{t("voice_ui.keep_editing")}</button>
            <button type="button" onClick={() => { const proceed = leaving; discard(); setLeaving(null); proceed(); }}>{t("voice_ui.discard_leave")}</button>
        </dialog>,
    };
}
