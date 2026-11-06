import { useEffect, useId, useRef, useState } from "react";
import { useI18n } from "@useI18n";
import { rebaseDraft } from "./draftRebase";
import { changedPaths, setSaveBarEntry } from "./saveBar";

// A write is confirmed by its own response, including backend normalization.
// `write` sends a draft; with it the form is saved from the config page top
// bar, which lists the changed fields by `label(path)`. `canSave` may be a
// function of the draft. `pending` (a list, or a function of the draft) names
// changes that are not in the draft,
// e.g. an engine the backend has not selected yet.
// `patch` sends only changed top-level fields to setters that merge them.
export function useSettingsDraft(saved, error, updateError, { write, canSave = true, label = path => path.join("."), pending = [], savedFromResponse = value => value, patch = false } = {}) {
    const { t } = useI18n();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const submitted = useRef(null);
    const [awaitingResponse, setAwaitingResponse] = useState(false);
    const savedKey = JSON.stringify(saved);
    const previousSavedKey = useRef(savedKey);
    const dirty = draft !== null && (JSON.stringify(draft) !== savedKey || awaitingResponse);
    const current = useRef({ draft, dirty });
    current.current = { draft, dirty };
    useEffect(() => {
        if (saved == null) return;
        if (current.current.draft === null) setDraft(saved);
        else {
            const rebased = rebaseDraft(JSON.parse(previousSavedKey.current), current.current.draft, saved);
            // Even a newer edit back to the old saved value must survive the
            // atom update that arrives just before this write's response.
            setDraft(submitted.current ? rebaseDraft(submitted.current.draft, current.current.draft, rebased) : rebased);
        }
        previousSavedKey.current = savedKey;
    }, [savedKey, saved]);
    useEffect(() => { if (error) setSaving(false); }, [error]);
    useEffect(() => {
        if (!saving) return;
        const timer = setTimeout(() => { setSaving(false); updateError("save_unconfirmed"); }, 5000);
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
    const discard = () => { setDraft(saved); setSaving(false); setAwaitingResponse(false); submitted.current = null; updateError(null); };
    useEffect(() => () => { submitted.current = null; }, []);
    const submit = async send => {
        if (saving) return;
        updateError(null);
        const request = { draft };
        submitted.current = request;
        setAwaitingResponse(true);
        setSaving(true);
        try {
            const value = patch ? Object.fromEntries(Object.entries(draft).filter(([key, value]) =>
                JSON.stringify(value) !== JSON.stringify(saved?.[key]))) : draft;
            const response = await send(value);
            if (submitted.current !== request) return;
            if (response?.status === 200) {
                const canonical = savedFromResponse(response.result);
                setDraft(value => rebaseDraft(request.draft, value, canonical));
                previousSavedKey.current = JSON.stringify(canonical);
                setSaving(false);
                submitted.current = null;
                setAwaitingResponse(false);
                updateError(null);
            } else if (response === false || response?.status) {
                setSaving(false);
                submitted.current = null;
                setAwaitingResponse(false);
            }
        } catch {
            if (submitted.current !== request) return;
            setSaving(false);
            submitted.current = null;
            setAwaitingResponse(false);
            updateError("save_unconfirmed");
        }
    };
    const saveState = error || (!saving && awaitingResponse) ? "save_failed" : saving ? "saving" : dirty ? "unsaved" : "saved";
    const id = useId();
    const changes = draft === null ? [] : [...changedPaths(saved, draft).map(label), ...(typeof pending === "function" ? pending(draft) : pending)];
    // `edited`: the draft differs or its write is unconfirmed. A `pending` change alone (e.g. the RVC
    // page selecting RVC) is not an edit the user would lose by leaving.
    const entry = { dirty: dirty || changes.length > 0, edited: dirty, saving, saveState, changes, canSave: !!write && draft !== null && !!(typeof canSave === "function" ? canSave(draft) : canSave),
        save: () => submit(write), discard };
    const entryRef = useRef(entry);
    entryRef.current = entry;
    const entryKey = JSON.stringify([entry.dirty, dirty, saving, saveState, changes, entry.canSave]);
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
