import clsx from "clsx";
import styles from "./EnvReadout.module.scss";

// What this PC and session report now (DESIGN.md "Environment readout"): GPU
// and memory, server state, download progress, model support. The words carry
// the state; tone only colors them ("neutral", "active", "warning", "failed").
// Readouts that change while the page is open are announced as a status.
export const EnvReadout = ({ tone = "neutral", live = true, actions = null, className, children }) =>
    <div className={clsx(styles.readout, styles[tone], className)}>
        <div className={styles.text} role={live ? "status" : undefined}>{children}</div>
        {actions && <div className={styles.actions}>{actions}</div>}
    </div>;
