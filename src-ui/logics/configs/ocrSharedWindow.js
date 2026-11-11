// Pure helpers for sharing a window with Chat Transcribe (Linux, Wayland).
//
// The desktop's ScreenCast portal lets the user pick a window; the Tauri side
// (`screencast_start`) asks it and the backend reads the frames. Nothing here
// asks on its own: the page calls `screencast_start` only from the button.

export const INITIAL_SHARED_WINDOW = Object.freeze({ supported: null, active: false, busy: false, error: null });

// Codes after which the token that was sent is used up: the desktop showed its
// dialog instead of restoring (and the user cancelled), or refused the request.
const TOKEN_SPENT = ["portal_cancelled", "portal_request_failed"];

// The token to keep after one attempt. The desktop hands out a new one on every
// success and each can be used once; "" means there is nothing to restore.
export const nextRestoreToken = (current, outcome) => {
    const kept = typeof current === "string" ? current : "";
    if (outcome?.ok === true) return typeof outcome.token === "string" ? outcome.token : "";
    return TOKEN_SPENT.includes(outcome?.code) ? "" : kept;
};

// Why sharing could not start, as an i18n key. Cancelling the dialog is the user's
// answer, not an error.
export const shareErrorKey = code => {
    if (!code || code === "portal_cancelled") return null;
    if (code === "screencast_unsupported") return "config_page.ocr.shared_window.error_unsupported";
    if (code === "portal_timeout" || code === "screencast_stream_timeout") return "config_page.ocr.shared_window.error_timeout";
    return "config_page.ocr.shared_window.error_failed";
};

// What the settings section shows. `state` is the shared-window atom.
export const sharedWindowView = state => {
    const current = state ?? INITIAL_SHARED_WINDOW;
    if (current.supported !== true) return { visible: false };
    const errorKey = current.active ? null : shareErrorKey(current.error);
    return {
        visible: true,
        statusKey: `config_page.ocr.shared_window.${current.busy ? "status_asking" : current.active ? "status_active" : "status_idle"}`,
        tone: errorKey ? "failed" : current.active ? "active" : "neutral",
        errorKey,
        errorCode: errorKey ? String(current.error) : null,
        shareKey: `config_page.ocr.shared_window.${current.active ? "share_another" : "share"}`,
        canShare: !current.busy,
        canStop: current.active && !current.busy,
    };
};

// A start error that reads differently where a window can be shared: on a Wayland desktop the
// VRChat window may exist and still not be found by its name. null: use the usual notice.
export const startErrorKey = (error_code, state) => error_code === "OCR_DISABLED_WINDOW_NOT_FOUND" && state?.supported === true
    ? "common_error.ocr_window_not_found_wayland" : null;

// Turning chat reading off ends the sharing. A start that failed never was "on",
// and waiting for the backend's answer (pending) changes nothing.
export const shouldStopSharing = (wasOn, isOn, active) => wasOn === true && isOn === false && active === true;

// The notice for sharing that ended without the app asking for it.
export const endedNotice = reason => reason === "ended"
    ? { status: "warning", key: "config_page.ocr.shared_window.notice_ended" }
    : { status: "error", key: "config_page.ocr.shared_window.notice_failed" };

// The actions behind the button, independent of React and Tauri so they can be tested:
//   invoke(command, args)  the Tauri command call
//   read() / write(state)  the shared-window atom
//   token() / saveToken(v) the saved restore token (config key OCR_PORTAL_RESTORE_TOKEN)
export const createSharedWindowActions = ({ invoke, read, write, token, saveToken }) => {
    const patch = change => write({ ...INITIAL_SHARED_WINDOW, ...read(), ...change });
    const support = async () => {
        try {
            const answer = await invoke("screencast_support");
            return { supported: answer?.supported === true, active: answer?.active === true };
        } catch {
            return { supported: false, active: false };
        }
    };
    return {
        // Is there a button to show on this desktop, and is a window shared already?
        refresh: async () => patch(await support()),
        // Ask the desktop for a window. With `choose`, the saved choice is not restored, so the
        // desktop shows its dialog: the way to pick a different window.
        share: async ({ choose = false } = {}) => {
            if (read()?.busy) return;
            patch({ busy: true, error: null });
            const saved = token() ?? "";
            const sent = choose ? "" : saved;
            try {
                const started = await invoke("screencast_start", { restoreToken: sent || null });
                const next = nextRestoreToken(saved, { ok: true, token: started?.restore_token });
                if (next !== saved) saveToken(next);
                patch({ supported: true, active: true, busy: false, error: null });
            } catch (error) {
                const code = typeof error === "string" && error ? error : "screencast_failed";
                // A token that was not sent (the user asked to choose) is still good.
                const next = sent ? nextRestoreToken(saved, { ok: false, code }) : saved;
                if (next !== saved) saveToken(next);
                // A sharing that was running may have been replaced by this request: ask what is true now.
                patch({ ...(await support()), busy: false, error: code });
            }
        },
        stop: async () => {
            try {
                await invoke("screencast_stop");
            } catch { /* nothing was shared */ }
            patch({ active: false, error: null });
        },
        // The desktop or the shared window ended it.
        ended: () => patch({ active: false }),
    };
};
