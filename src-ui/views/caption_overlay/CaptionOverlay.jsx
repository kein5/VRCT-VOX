import { useEffect, useLayoutEffect, useState } from "react";
import clsx from "clsx";
import { captionOverlayBridge } from "../../logics/captionOverlay/bridge";
import { nextChange, visibleLines } from "../../logics/captionOverlay/lines";
import { speakerLabels } from "../../logics/common/speakerLabels";
import styles from "./CaptionOverlay.module.scss";

// The colours a voice can take (CaptionOverlay.module.scss); the fifth voice starts over.
const VOICE_COLOURS = 4;
// "A" is 0, "B" is 1, ... "Z" is 25, "AA" is 26: the order the server first heard the voices in.
const voiceIndex = label => [...label].reduce((value, letter) => value * 26 + letter.charCodeAt(0) - 64, 0) - 1;

// Captions over the desktop. The window lets clicks through and never has the
// focus, so nothing here can be operated: it only draws what the main window
// handed over, and drops each line when its time has passed.
export const CaptionOverlay = ({ bridge = captionOverlayBridge, now = Date.now }) => {
    const [snapshot, setSnapshot] = useState(null);
    const [, setTick] = useState(0);

    useEffect(() => {
        let disposed = false, revision = 0;
        const refresh = async () => {
            const current = ++revision;
            try {
                const next = await bridge.snapshot();
                if (!disposed && current === revision) setSnapshot(next);
            } catch (error) { console.warn("Caption overlay could not read its captions", error); }
        };
        const off = bridge.onChanged(refresh);
        off.then(refresh, () => {});
        return () => { disposed = true; off.then(stop => stop(), () => {}); };
    }, [bridge]);

    useLayoutEffect(() => {
        if (!snapshot) return;
        const root = document.documentElement.style;
        root.setProperty("--caption_font_size", `${snapshot.font_size}px`);
        root.setProperty("--caption_plate", String(snapshot.opacity));
        root.setProperty("--caption_font_family", JSON.stringify(snapshot.font_family));
    }, [snapshot?.font_size, snapshot?.opacity, snapshot?.font_family]);

    // Draw again when the next line starts to fade or goes.
    useEffect(() => {
        if (!snapshot) return undefined;
        const at = nextChange(snapshot.lines, now());
        if (at === null) return undefined;
        const timer = setTimeout(() => setTick(tick => tick + 1), Math.max(20, at - now()));
        return () => clearTimeout(timer);
    });

    const lines = snapshot ? visibleLines(snapshot.lines, now()) : [];
    return (
        <div className={clsx(styles.container, { [styles.is_top]: snapshot?.position === "top" })}>
            {lines.map(line => {
                // Who spoke, where the game audio's voices were told apart: "A", or "A·B" for two in one line.
                const speakers = line.kind === "received" ? speakerLabels(line.speakers) : [];
                const who = speakers.length ? <span key="who" className={styles.who}>{speakers.join("·")}</span> : null;
                // The label leads the first paragraph of the line, the original or else the translation.
                const lead = (text, first) => first && who ? [who, text] : text;
                return (
                    <div key={line.id} className={clsx(styles.line, styles[line.kind],
                        speakers.length > 0 && styles[`voice_${voiceIndex(speakers[0]) % VOICE_COLOURS}`], {
                            [styles.is_fading]: line.fading, [styles.is_pending]: line.pending,
                        })}>
                        {line.text && <p className={styles.text}>{lead(line.text, true)}</p>}
                        {line.translations.map((text, index) => (
                            <p key={index} className={styles.translation}>{lead(text, !line.text && index === 0)}</p>
                        ))}
                    </div>
                );
            })}
        </div>
    );
};
