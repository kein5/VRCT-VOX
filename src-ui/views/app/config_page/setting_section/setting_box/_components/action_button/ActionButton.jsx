import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import styles from "./ActionButton.module.scss";

export const ActionButton = ({
    IconComponent,
    ClickedIconComponent,
    clicked_duration = 1000,
    onclickFunction,
    onErrorFunction,
    label,
}) => {
    const [is_clicked, setIsClicked] = useState(false);
    const [is_pending, setIsPending] = useState(false);
    const running = useRef(false);
    const mounted = useRef(true);
    const timer_ref = useRef(null);

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; clearTimeout(timer_ref.current); };
    }, []);

    const onClick = async () => {
        if (running.current) return;
        running.current = true;
        setIsPending(true);
        try {
            await onclickFunction?.();
            if (mounted.current && ClickedIconComponent) {
                setIsClicked(true);
                timer_ref.current = setTimeout(() => { running.current = false; setIsClicked(false); }, clicked_duration);
            } else {
                running.current = false;
            }
        } catch (error) {
            running.current = false;
            if (mounted.current) onErrorFunction?.(error);
        } finally {
            if (mounted.current) setIsPending(false);
        }
    };

    const ShownIcon = is_clicked && ClickedIconComponent ? ClickedIconComponent : IconComponent;
    const active_class = { [styles.is_clicked]: is_clicked };

    return (
        <div className={styles.container}>
            <button type="button" className={clsx(styles.button_wrapper, active_class)} onClick={onClick}
                aria-disabled={is_pending || is_clicked} aria-busy={is_pending}
                aria-label={typeof label === "string" ? label : undefined}>
                <ShownIcon className={clsx(styles.button_svg, active_class, { [styles.is_pending]: is_pending })} aria-hidden="true" />
                {is_pending && <span className={styles.loader} aria-hidden="true" />}
            </button>
        </div>
    );
};

