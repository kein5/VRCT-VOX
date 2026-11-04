import { useEffect, useRef } from "react";

const available = element => element?.isConnected && !element.disabled && !element.matches?.(":disabled") &&
    element.getAttribute("aria-disabled") !== "true";

// Close synchronously before removing the dialog. Restore focus after the commit,
// when download startup may have disabled or replaced the review button.
export function useConsentDialog(open, fallback) {
    const dialog = useRef(null);
    const opener = useRef(null);
    useEffect(() => {
        if (!open) {
            opener.current = null;
            return;
        }
        const node = dialog.current;
        // StrictMode replays this effect after closing the dialog, when focus is
        // already on the body. Keep the element that opened the dialog.
        const active = document.activeElement;
        if (!opener.current && active && active !== document.body && !node?.contains?.(active)) opener.current = active;
        const trigger = opener.current;
        const nearby = trigger?.closest("[data-model-download], [data-setting-id]");
        node?.showModal();
        return () => {
            if (node?.open) node.close();
            queueMicrotask(() => {
                // React StrictMode may already have reopened this same dialog.
                if (node?.open) return;
                if (available(trigger)) { trigger.focus(); return; }
                const scope = nearby?.isConnected ? nearby : fallback?.current;
                const control = [...(scope?.querySelectorAll("button, input, select, summary, [tabindex]") ?? [])]
                    .find(element => available(element) && !element.closest("dialog") && element.tabIndex >= 0);
                if (control) control.focus();
                // All actions may be busy. The caller's labelled section remains
                // focusable even when the nearer template wrapper is not.
                else if (fallback?.current?.isConnected) fallback.current.focus();
                else if (scope?.isConnected) { scope.tabIndex = -1; scope.focus(); }
            });
        };
    }, [open, fallback]);
    const close = () => { if (dialog.current?.open) dialog.current.close(); };
    return { dialog, close };
}
