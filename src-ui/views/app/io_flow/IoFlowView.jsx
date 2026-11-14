import { useMemo } from "react";
import clsx from "clsx";
import { useI18n } from "@useI18n";
import { createLanguageNames } from "../../../logics/common/languageNames.js";
import { formatMs, latestTraces, median, timelineScale, traceTotal } from "../../../logics/flow/ioFlow.js";
import { flowNote, offGroups, outputDetail, outputTime, timelineRows } from "../../../logics/flow/flowText.js";
import styles from "./IoFlowView.module.scss";

const HISTORY = 20;

// Where the user's voice and typed chat go with the current settings, and how long the
// latest of each took to reach each output. Shared by the main window's panel and the VR
// window; it only reads, and changes nothing. Every duration is in ms.
// Compact (VR, which cannot scroll): outputs are short labels, and one timeline follows
// for the newest input of either lane.
export const IoFlowView = ({ flow, traces, compact = false }) => {
    const { t, i18n } = useI18n();
    const names = useMemo(() => createLanguageNames(i18n.language), [i18n.language]);
    if (!flow) return <p className={styles.waiting} role="status">{t("io_flow.loading")}</p>;
    const note = flowNote(flow, t);
    const newest = latestTraces(traces, 1)[0] ?? null;
    return <div className={clsx(styles.view, { [styles.compact]: compact })}>
        {["voice", "chat"].map(input => <Lane key={input} input={input} lane={flow[input]} names={names}
            traces={latestTraces(traces, HISTORY, input)} compact={compact} />)}
        {compact && <section className={styles.newest} aria-label={t("io_flow.newest")}>
            <h3 className={styles.lane_title}>{t("io_flow.newest")}
                {newest && <span className={styles.lane_state}>{t(`io_flow.${newest.input}`)}</span>}</h3>
            <Latest trace={newest} history={[]} compact />
        </section>}
        {note && <p className={styles.live}>{note}</p>}
    </div>;
};

const Lane = ({ input, lane, traces, names, compact }) => {
    const { t } = useI18n();
    const latest = traces[0] ?? null;
    const recognition = lane.recognition;
    const translation = lane.translation;
    const used = lane.outputs.filter(row => row.on);
    return <section className={clsx(styles.lane, { [styles.lane_off]: !lane.on })} aria-label={t(`io_flow.${input}`)}>
        <h3 className={styles.lane_title}>{t(`io_flow.${input}`)}
            {input === "voice" && !lane.on && <span className={styles.lane_state}>{t("io_flow.mic_off_lane")}</span>}
        </h3>
        <ol className={styles.stages}>
            {recognition && <li className={styles.stage}>{t("io_flow.stage.recognition")}
                <span className={styles.stage_detail}>{recognition.realtime ? t("io_flow.recognition_realtime") : recognition.engine}</span></li>}
            <li className={clsx(styles.stage, { [styles.is_off]: !translation.on })}>{t("io_flow.stage.translate")}
                <span className={styles.stage_detail}>{translation.on
                    ? `${names.language(translation.source)} → ${translation.targets.map(name => names.language(name)).join(" / ")}`
                    : t("io_flow.translation_off")}</span></li>
        </ol>
        {compact
            ? <ul className={styles.pills}>
                {used.map(row => {
                    const time = outputTime(row, latest, t);
                    return <li key={row.id} className={styles.pill}>{t(`io_flow.output.${row.id}`)}
                        {time && <span className={styles.pill_time}>{time}</span>}</li>;
                })}
            </ul>
            : <ul className={styles.outputs}>
                {used.map(row => <li key={row.id} className={styles.output}>
                    <span className={styles.output_name}>{t(`io_flow.output.${row.id}`)}</span>
                    <span className={styles.output_detail}>{outputDetail(row, t, names)}</span>
                    <span className={styles.output_time}>{outputTime(row, latest, t) ?? ""}</span>
                </li>)}
            </ul>}
        {/* VR cannot scroll: there the unused outputs share one line. */}
        {(compact ? [offGroups(lane.outputs, t)] : offGroups(lane.outputs, t).map(group => [group]))
            .filter(groups => groups.length > 0).map(groups => <p key={groups[0].reason} className={styles.unused}>
                {groups.map(group => t("io_flow.unused", { outputs: group.outputs, reason: group.text })).join(t("io_flow.group_separator"))}</p>)}
        {!compact && <Latest trace={latest} history={traces} />}
    </section>;
};

const Latest = ({ trace, history, compact = false }) => {
    const { t } = useI18n();
    if (!trace) return <p className={styles.no_trace}>{t("io_flow.no_trace")}</p>;
    const total = traceTotal(trace);
    const scale = timelineScale(total ?? 0);
    const totals = history.map(traceTotal).filter(Number.isInteger);
    return <div className={styles.latest}>
        <p className={styles.latest_head}>
            <span className={styles.latest_text}>{t("io_flow.latest_text", { text: trace.text })}</span>
            <span className={styles.latest_total}>{t("io_flow.total")} {formatMs(total)}</span>
        </p>
        {!compact && <p className={styles.origin}>{t(`io_flow.origin.${trace.origin}`)}</p>}
        <Timeline rows={timelineRows(trace, t)} scale={scale} />
        {!compact && totals.length > 1 && <History totals={totals.slice().reverse()} middle={median(totals)} />}
    </div>;
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
