import { useMemo } from "react";
import clsx from "clsx";
import { useI18n } from "@useI18n";
import { createLanguageNames } from "../../../logics/common/languageNames.js";
import { formatMs, latestTraces, median, timelineScale, traceTotal } from "../../../logics/flow/ioFlow.js";
import { flowNote, offGroups, timelineRows } from "../../../logics/flow/flowText.js";
import { buildFlowGraph } from "../../../logics/flow/flowGraph.js";
import { FlowGraph } from "./FlowGraph";
import styles from "./IoFlowView.module.scss";

const HISTORY = 20;

// Where the user's voice and typed chat go with the current settings, drawn as a graph,
// and how long the latest of each took. Shared by the main window's panel and the VR
// window; it only reads, and changes nothing. Every duration is in ms.
// Compact (VR, which cannot scroll): one timeline, for the newest input of either lane.
export const IoFlowView = ({ flow, traces, compact = false }) => {
    const { t, i18n } = useI18n();
    const names = useMemo(() => createLanguageNames(i18n.language), [i18n.language]);
    const graph = useMemo(() => buildFlowGraph(flow, traces), [flow, traces]);
    if (!graph) return <p className={styles.waiting} role="status">{t("io_flow.loading")}</p>;
    const note = flowNote(flow, t);
    const unused = ["voice", "chat"].flatMap(lane => offGroups(flow[lane].outputs, t)
        .map(group => ({ lane, ...group })));
    return <div className={clsx(styles.view, { [styles.compact]: compact })}>
        <div className={styles.graph_scroll}><FlowGraph graph={graph} names={names} compact={compact} /></div>
        {unused.length > 0 && !compact && <ul className={styles.unused}>
            {unused.map(group => <li key={`${group.lane}:${group.reason}`}>
                <span className={clsx(styles.lane_mark, styles[`mark_${group.lane}`])}>{t(`io_flow.lane_short.${group.lane}`)}</span>
                {t("io_flow.unused", { outputs: group.outputs, reason: group.text })}</li>)}
        </ul>}
        {compact
            ? <Latest trace={latestTraces(traces, 1)[0] ?? null} history={[]} compact />
            : <div className={styles.latest_pair}>
                {["voice", "chat"].map(lane => <Latest key={lane} lane={lane}
                    trace={latestTraces(traces, 1, lane)[0] ?? null} history={latestTraces(traces, HISTORY, lane)} />)}
            </div>}
        {note && <p className={styles.live}>{note}</p>}
    </div>;
};

const Latest = ({ trace, history, lane = null, compact = false }) => {
    const { t } = useI18n();
    const title = lane ? t(`io_flow.${lane}`) : trace ? t(`io_flow.${trace.input}`) : t("io_flow.newest");
    if (!trace) return <section className={styles.latest}><h3 className={styles.latest_title}>{title}</h3>
        <p className={styles.no_trace}>{t("io_flow.no_trace")}</p></section>;
    const total = traceTotal(trace);
    const scale = timelineScale(total ?? 0);
    const totals = history.map(traceTotal).filter(Number.isInteger);
    return <section className={clsx(styles.latest, styles[`latest_${trace.input}`])} aria-label={title}>
        <h3 className={styles.latest_title}>{title}</h3>
        <p className={styles.latest_head}>
            <span className={styles.latest_text}>{t("io_flow.latest_text", { text: trace.text })}</span>
            <span className={styles.latest_total}>{t("io_flow.total")} {formatMs(total)}</span>
        </p>
        {!compact && <p className={styles.origin}>{t(`io_flow.origin.${trace.origin}`)}</p>}
        <Timeline rows={timelineRows(trace, t)} scale={scale} />
        {!compact && totals.length > 1 && <History totals={totals.slice().reverse()} middle={median(totals)} />}
    </section>;
};

// One row per stage or output. Bars share the axis, rounded up to a readable step.
export const Timeline = ({ rows, scale, className }) => {
    const { t } = useI18n();
    return <div className={clsx(styles.timeline, className)} role="list" aria-label={t("io_flow.timeline", { scale })}>
        {rows.map((row, index) => <div key={index} role="listitem" className={clsx(styles.row, { [styles.is_off]: row.off })}>
            <span className={styles.row_label}>{row.label}</span>
            <span className={clsx(styles.track, { [styles.no_track]: row.off })} aria-hidden="true">
                {!row.off && <span className={clsx(styles.bar, styles[`bar_${row.kind}`])}
                    style={{ left: `${(row.start / scale) * 100}%`, width: `${Math.max(.5, ((row.end - row.start) / scale) * 100)}%` }} />}
            </span>
            <span className={styles.row_value}>{row.value}</span>
        </div>)}
        <div className={clsx(styles.row, styles.axis_row)} aria-hidden="true">
            <span /><span className={styles.axis}><span>0 ms</span><span>{scale} ms</span></span><span />
        </div>
    </div>;
};

// The totals of recent messages, oldest on the left, with their median.
const History = ({ totals, middle }) => {
    const { t } = useI18n();
    const top = Math.max(...totals, 1);
    return <div className={styles.history}>
        <span className={styles.bars} aria-hidden="true">
            {totals.map((value, index) => <span key={index} className={clsx(styles.spark, { [styles.is_last]: index === totals.length - 1 })}
                style={{ height: `${Math.max(8, (value / top) * 100)}%` }} />)}
        </span>
        <span className={styles.history_text}>{t("io_flow.median", { count: totals.length, value: formatMs(middle) })}</span>
    </div>;
};
