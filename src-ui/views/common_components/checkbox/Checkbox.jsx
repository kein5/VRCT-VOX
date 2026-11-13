import clsx from "clsx";
import styles from "./Checkbox.module.scss";
export const Checkbox = ({
    label,
    variable,
    is_available = true,
    toggleFunction,
    size = "2.8rem",
    borderWidth = "0.2rem",
    padding = "1.8rem",
    "aria-describedby": describedBy,
}) => {
    const is_pending = variable.state === "pending";
    const unavailable = !is_available || is_pending;

    const wrapper_class_names = clsx(styles.checkbox_wrapper, {
        [styles.is_disabled]: !is_available,
        [styles.is_pending]: variable.state === "pending",
    });

    return (
        <div className={styles.checkbox_container}>
            <label
                className={wrapper_class_names}
                style={{
                    "--checkbox-size": size,
                    "--checkbox-border-width": borderWidth,
                    "--checkbox-padding": padding,
                }}
            >
                <input
                    type="checkbox"
                    aria-label={label}
                    aria-describedby={describedBy}
                    aria-busy={is_pending}
                    aria-disabled={unavailable}
                    checked={variable.data}
                    onClick={(e) => {
                        e.stopPropagation();
                        if (unavailable) e.preventDefault();
                    }}
                    onKeyDown={(e) => {
                        if (unavailable && (e.key === " " || e.key === "Enter")) e.preventDefault();
                    }}
                    onChange={() => {
                        if (!unavailable && toggleFunction) {
                            toggleFunction();
                        }
                    }}
                />
                <span className={styles.cbx} aria-hidden="true">
                    <svg viewBox="0 0 12 12">
                        <polyline points="1.2 6.79411765 4.6 10.5 11.1 1.5" pathLength="1"></polyline>
                    </svg>
                </span>
                {is_pending && <span className={styles.loader} aria-hidden="true"></span>}
            </label>
        </div>
    );
};
