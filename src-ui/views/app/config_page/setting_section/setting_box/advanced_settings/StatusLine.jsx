import clsx from "clsx";
import styles from "./VoiceSettings.module.scss";

// One line at the top of a feature page that says what it is doing now. The
// dot only repeats the words; tone is "active", "pending", "failed" or "idle".
export const StatusLine = ({ tone = "idle", children, actions = null }) => <div className={styles.statusLine}>
    <p role="status" className={clsx(styles.statusText, styles[`tone_${tone}`])}><span aria-hidden="true" className={styles.statusDot} />{children}</p>
    {actions}
</div>;
