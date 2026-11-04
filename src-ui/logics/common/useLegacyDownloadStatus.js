import { useEffect, useRef, useState } from "react";

export const legacyDownloadPhase = option => Number.isFinite(option.progress)
    ? option.progress >= 100 ? "finalizing" : "downloading"
    : option.is_pending ? "pending" : option.is_downloaded ? "complete" : "stopped";

// Announce phases immediately, percentages at ten-point intervals and at most
// once a second. Keep a trailing update so the last received value is not lost.
export function useLegacyDownloadStatus(option, model, t) {
    const [status, setStatus] = useState("");
    const announced = useRef({ phase: null, model, at: 0, active: false });
    const phase = legacyDownloadPhase(option);
    const progress = Math.floor(Math.max(0, Math.min(100, option.progress || 0)) / 10) * 10;
    useEffect(() => {
        const previous = announced.current;
        const active = ["pending", "downloading", "finalizing"].includes(phase);
        if (!active && (!previous.active || previous.model !== model)) return;
        const publish = () => {
            setStatus(t(`legacy_model_downloads.progress_${phase}`, { model, progress }));
            announced.current = { phase, model, at: Date.now(), active };
        };
        if (phase !== previous.phase || model !== previous.model) { publish(); return; }
        const timer = setTimeout(publish, Math.max(0, 1000 - (Date.now() - previous.at)));
        return () => clearTimeout(timer);
    }, [phase, progress, model, t]);
    return status;
}
