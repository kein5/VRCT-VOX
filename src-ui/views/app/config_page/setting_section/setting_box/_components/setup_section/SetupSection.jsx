import { useState } from "react";
import styles from "./SetupSection.module.scss";

// One-time setup on a page (models, runtimes, downloads, servers), folded
// (DESIGN.md "Roles in settings"). The summary carries a one-line status, so it
// can stay closed. `attention` opens it while something in it needs the user.
export const SetupSection = ({ title, status, attention = false, children }) => {
    const [opened, setOpened] = useState(false);
    return <details data-setup className={styles.setup} open={opened || attention}
        onToggle={event => setOpened(event.currentTarget.open)}>
        <summary><span className={styles.title}>{title}</span>{status && <span className={styles.status}>{status}</span>}</summary>
        <div className={styles.body}>{children}</div>
    </details>;
};
