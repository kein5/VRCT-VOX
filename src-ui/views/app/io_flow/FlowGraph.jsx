import { useLayoutEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useI18n } from "@useI18n";
import { formatMs } from "../../../logics/flow/ioFlow.js";
import { outputDetail } from "../../../logics/flow/flowText.js";
import { splitFeatureLabel } from "../../../logics/common/featureLabel.js";
import styles from "./FlowGraph.module.scss";

const ENGINE_NAMES = { rvc: "RVC", "seed-vc": "Seed-VC" };
// Where each box sits: [column, first row, last row + 1] on a 5 x 6 grid.
const PLACE = {
    in_voice: [1, 1, 3], recognition: [2, 1, 3], translate_voice: [3, 1, 3],
    speech: [4, 2, 4], conversion: [4, 4, 6],
    in_chat: [1, 5, 7], translate_chat: [3, 5, 7],
    chatbox: [5, 1, 2], live_voice: [5, 2, 3], desktop_caption: [5, 3, 4],
    vr_log: [5, 4, 5], clipboard: [5, 5, 6], websocket: [5, 6, 7],
};

// Which input reaches which output, as boxes and arrows. The boxes are HTML on a grid, so
// long Japanese labels wrap and stay readable at any width; the arrows are measured from
// the boxes and drawn behind them. The newest message's path is lit, and pulses once when
// a new message arrives (not under reduced motion).
export const FlowGraph = ({ graph, names, compact = false }) => {
    const { t } = useI18n();
    const root = useRef(null);
    const [paths, setPaths] = useState([]);

    useLayoutEffect(() => {
        const container = root.current;
        if (!container || !graph) return undefined;
        const measure = () => {
            const base = container.getBoundingClientRect();
            // The VR window enlarges its content (CSS zoom): measured boxes are in screen pixels,
            // the arrows in the graph's own. Divide by that scale.
            const scale = container.offsetWidth > 0 ? base.width / container.offsetWidth : 1;
            const box = id => {
                const element = container.querySelector(`[data-node="${id}"]`);
                if (!element) return null;
                const rect = element.getBoundingClientRect();
                const left = (rect.left - base.left) / scale, top = (rect.top - base.top) / scale;
                const width = rect.width / scale, height = rect.height / scale;
                return { left, right: left + width, top, bottom: top + height, mid: top + height / 2, center: left + width / 2 };
            };
            // Unused routes are not drawn: their boxes are dashed and say why. The dotted line
            // for VRChat reading the microphone itself stays, as it is how the voice gets there.
            setPaths(graph.edges.filter(row => row.on || row.direct).map(row => {
                const from = box(row.from), to = box(row.to);
                if (!from || !to) return null;
                // The live voice leaves the microphone from below, under the text stages.
                if (row.from === "in_voice" && (row.to === "conversion" || row.to === "live_voice")) {
                    const x = from.center, y = from.bottom;
                    return { ...row, d: `M${x},${y} C${x},${to.mid} ${to.left - 60},${to.mid} ${to.left - 4},${to.mid}` };
                }
                // Boxes stacked in one column (speech above its conversion) join straight down.
                if (Math.abs(from.center - to.center) < 8 && to.top > from.bottom) {
                    return { ...row, d: `M${from.center},${from.bottom} L${to.center},${to.top - 4}` };
                }
                const x1 = from.right, y1 = from.mid, x2 = to.left - 4, y2 = to.mid, bend = Math.max(24, (x2 - x1) / 2);
                return { ...row, d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}` };
            }).filter(Boolean));
        };
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(container);
        return () => observer.disconnect();
    }, [graph]);

    if (!graph) return null;
    // Unused arrows first, then used ones, then the lit path on top.
    const ordered = [...paths].sort((a, b) => (a.on - b.on) || (a.lit - b.lit));
    return <div ref={root} className={clsx(styles.graph, { [styles.compact]: compact })} role="group" aria-label={t("io_flow.graph")}>
        <svg className={styles.edges} aria-hidden="true">
            <defs>
                {["on", "off", "lit"].map(kind => <marker key={kind} id={`flow-arrow-${kind}`} viewBox="0 0 8 8" refX="7" refY="4"
                    markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" className={styles[`head_${kind}`]} /></marker>)}
            </defs>
            {ordered.map(row => <path key={row.id} d={row.d} className={clsx(styles.edge, styles[`lane_${row.lane}`], {
                [styles.off]: !row.on, [styles.direct]: row.direct, [styles.lit]: row.lit })}
                markerEnd={`url(#flow-arrow-${row.lit ? "lit" : row.on ? "on" : "off"})`} />)}
            {ordered.filter(row => row.lit).map(row => <path key={`${graph.pulse}:${row.id}`} d={row.d}
                className={clsx(styles.pulse, styles[`lane_${row.lane}`])} />)}
        </svg>
        {graph.nodes.map(row => {
            const [column, start, end] = PLACE[row.id];
            return <div key={row.id} data-node={row.id} style={{ gridColumn: column, gridRow: `${start} / ${end}` }}
                className={clsx(styles.node, styles[`kind_${row.kind}`], row.lane && styles[`lane_${row.lane}`], { [styles.off]: !row.on })}>
                <NodeText row={row} names={names} t={t} />
            </div>;
        })}
    </div>;
};

// A feature's name breaks before its short name in brackets, never inside a word.
const FeatureName = ({ text }) => {
    const { name, abbr } = splitFeatureLabel(text);
    return <span className={styles.name}>{name}{abbr && <span className={styles.abbr}>{abbr}</span>}</span>;
};

const NodeText = ({ row, names, t }) => {
    const ms = value => Number.isInteger(value) ? formatMs(value) : null;
    if (row.kind === "input") return <>
        <span className={styles.name}>{t(`io_flow.${row.lane}`)}</span>
        {!row.on && <span className={styles.detail}>{t("io_flow.mic_off_short")}</span>}
    </>;
    if (row.id === "recognition") return <>
        <span className={styles.name}>{t("io_flow.stage.recognition")}</span>
        <span className={styles.detail}>{row.realtime ? t("io_flow.recognition_realtime") : row.engine}</span>
        {ms(row.ms) && <span className={styles.time}>{t(`io_flow.stage.${row.msKind}`)} {ms(row.ms)}</span>}
    </>;
    if (row.kind === "stage") return <>
        <span className={styles.name}>{t("io_flow.stage.translate")}</span>
        <span className={styles.detail}>{row.on
            ? `${names.language(row.translation.source)} → ${row.translation.targets.map(name => names.language(name)).join(" / ")}`
            : t("io_flow.translation_off")}</span>
        {row.on && ms(row.ms) && <span className={styles.time}>{ms(row.ms)}</span>}
    </>;
    if (row.kind === "speech") return <>
        <span className={styles.name}>{t("io_flow.output.speech")}</span>
        <span className={styles.detail}>{row.on && row.language
            ? t("io_flow.speech_language", { language: names.language(row.language) }) : t("io_flow.speech_off_short")}</span>
    </>;
    if (row.kind === "conversion") return <>
        <FeatureName text={ENGINE_NAMES[row.engine]
            ? t("io_flow.conversion_with", { engine: ENGINE_NAMES[row.engine] }) : t("io_flow.conversion")} />
        {ms(row.ms) && <span className={styles.time}>{t("io_flow.round_trip", { ms: row.ms })}</span>}
    </>;
    // An output: its name, then the latest time from each input, or what it does or why it is off.
    const times = ["voice", "chat"].filter(lane => Number.isInteger(row.times[lane]))
        .map(lane => `${t(`io_flow.lane_short.${lane}`)} ${formatMs(row.times[lane])}`);
    // What the output does for the input that uses it; when neither does, why it is off.
    const used = row.rows.voice?.on ? row.rows.voice : row.rows.chat?.on ? row.rows.chat : null;
    const detail = row.id === "live_voice" ? outputDetail(row.live, t, names)
        : outputDetail(used ?? row.rows.voice ?? row.rows.chat, t, names);
    return <>
        <span className={styles.name}>{t(`io_flow.output_node.${row.id}`)}</span>
        {times.length > 0 && <span className={styles.time}>{times.join(" · ")}</span>}
        <span className={styles.detail}>{detail}</span>
    </>;
};
