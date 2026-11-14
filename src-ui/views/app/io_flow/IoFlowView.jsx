import { useMemo } from "react";
import clsx from "clsx";
import { useI18n } from "@useI18n";
import { createLanguageNames } from "../../../logics/common/languageNames.js";
import { formatMs, latestTraces, median, timelineScale, traceTotal } from "../../../logics/flow/ioFlow.js";
import { flowNote, outputDetail, outputTime, timelineRows } from "../../../logics/flow/flowText.js";
import styles from "./IoFlowView.module.scss";

const HISTORY = 20;

// Where the user's voice and typed chat go with the current settings, and how long the
// latest of each took to reach each output. Shared by the main window's panel and the VR
// window; it only reads, and changes nothing. Every duration is in ms.
export const IoFlowView = ({ flow, traces, compact = false }) => {
    const { t, i18n } = useI18n();
    const names = useMemo(() => createLanguageNames(i18n.language), [i18n.language]);
    if (!flow) return <p className={styles.waiting} role="status">{t("io_flow.loading")}</p>;
    const note = flowNote(flow, t);
    return <div className={clsx(styles.view, { [styles.compact]: compact })}>
        {["voice", "chat"].map(input => <Lane key={input} input={input} lane={flow[input]} names={names}
            traces={latestTraces(traces, HISTORY, input)} compact={compact} />)}
        {note && <p className={styles.live}>{note}</p>}
    </div>;
};

const Lane = ({ input, lane, traces, names, compact }) => {
    const { t } = useI18n();
    const latest = traces[0] ?? null;
    const recognition = lane.recognition;
    const translation = lane.translation;
    return <section className={styles.lane} aria-label={t(`io_flow.${input}`)}>
        <h3 className={styles.lane_title}>{t(`io_flow.${input}`)}
            {input === "voice" && !lane.on && <span className={styles.lane_state}>{t("io_flow.reason.mic_off")}</span>}
        </h3>
        <ol className={styles.stages}>
            {recognition && <li className={styles.stage}>{t("io_flow.stage.recognition")}
                <span className={styles.stage_detail}>{recognition.realtime ? t("io_flow.recognition_realtime") : recognition.engine}</span></li>}
            <li className={clsx(styles.stage, { [styles.is_off]: !translation.on })}>{t("io_flow.stage.translate")}
                <span className={styles.stage_detail}>{translation.on
                    ? `${names.language(translation.source)} → ${translation.targets.map(name => names.language(name)).join(" / ")}`
                    : t("io_flow.translation_off")}</span></li>
        </ol>
        <ul className={styles.outputs}>
            {lane.outputs.map(row => {
                const time = outputTime(row, latest, t);
                return <li key={row.id} className={clsx(styles.output, { [styles.is_off]: !row.on })}>
                    <span className={styles.output_name}>{t(`io_flow.output.${row.id}`)}
                        <span className={styles.output_detail}>{outputDetail(row, t, names)}</span></span>
                    {time && <span className={styles.output_time}>{time}</span>}
                </li>;
            })}
        </ul>
        <Latest trace={latest} history={traces} compact={compact} />
    </section>;
};

const Latest = ({ trace, history, compact }) => {
    const { t } = useI18n();
    if (!trace) return <p className={styles.no_trace}>{t("io_flow.no_trace")}</p>;
    const total = traceTotal(trace);
    const scale = timelineScale(total ?? 0);
    const totals = history.map(traceTotal).filter(Number.isInteger);
    const middle = median(totals);
    return <div className={styles.latest}>
        <p className={styles.latest_head}>
            <span className={styles.latest_text}>{t("io_flow.latest")}「{trace.text}」</span>
            <span className={styles.latest_total}>{t("io_flow.total")} {formatMs(total)}</span>
        </p>
        <p className={styles.origin}>{t(`io_flow.origin.${trace.origin}`)}</p>
        <Timeline rows={timelineRows(trace, t)} scale={scale} />
        {!compact && totals.length > 1 && <History totals={totals.slice().reverse()} middle={middle} />}
    </div>;
};

// One row per stage or output. Bars share the axis, rounded up to a readable step.
export const Timeline = ({ rows, scale, className }) => {
    const { t } = useI18n();
    return <div className={clsx(styles.timeline, className)} role="list" aria-label={t("io_flow.timeline", { scale })}>
        {rows.map((row, index) => <div key={index} role="listitem" className={clsx(styles.row, { [styles.is_off]: row.off })}>
            <span className={styles.row_label}>{row.label}</span>
            <span className={styles.track} aria-hidden="true">
                {!row.off && <span className={clsx(styles.bar, styles[`bar_${row.kind}`])}
                    style={{ left: `${(row.start / scale) * 100}%`, width: `${Math.max(.5, ((row.end - row.start) / scale) * 100)}%` }} />}
            </span>
            <span className={styles.row_value}>{row.value}</span>
        </div>)}
        <div className={clsx(styles.row, styles.axis_row)} aria-hidden="true"><span /><span className={styles.axis}><span>0 ms</span><span>{scale} ms</span></span><span /></div>
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
