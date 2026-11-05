import React, { useEffect, useRef } from "react";
import clsx from "clsx";
import { useI18n } from "@useI18n";
import { Tooltip } from "@common_components";
import styles from "./MessageSubMenuContainer.module.scss";
import SendMessageSvg from "@images/send_message.svg?react";
import RefreshSvg from "@images/refresh_2.svg?react";

export const MessageSubMenuContainer = (props) => {
    const { t } = useI18n();
    const progressRef = useRef(null);
    const currentHold = useRef(null);

    const startHold = event => {
        if (event.button !== 0 || !event.isPrimary || currentHold.current) return;
        const hold = { pointerId: event.pointerId, target: event.currentTarget, timer: null };
        currentHold.current = hold;
        hold.target.setPointerCapture(hold.pointerId);
        if (progressRef.current) {
            progressRef.current.style.transition = "width 500ms linear";
            progressRef.current.style.width = "100%";
        }
        hold.timer = setTimeout(() => {
            if (currentHold.current !== hold) return;
            cancelHold();
            props.resendFunction();
            props.setIsHovered(false);
        }, 500);
    };

    const cancelHold = () => {
        const hold = currentHold.current;
        currentHold.current = null;
        if (hold) {
            clearTimeout(hold.timer);
            if (hold.target.hasPointerCapture(hold.pointerId)) hold.target.releasePointerCapture(hold.pointerId);
        }
        if (progressRef.current) {
            progressRef.current.style.transition = "none";
            progressRef.current.style.width = "0%";
        }
    };

    const moveHold = event => {
        const hold = currentHold.current;
        if (!hold || event.pointerId !== hold.pointerId) return;
        const rect = hold.target.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) cancelHold();
    };

    useEffect(() => {
        window.addEventListener("blur", cancelHold);
        return () => {
            window.removeEventListener("blur", cancelHold);
            cancelHold();
        };
    }, []);

    const onClickFunction = () => {
        props.editFunction();

    };

    const offset = {
        popper: {
            sx: {
                marginBottom: "0.2em"
            }
        }
    };

    return (
        <div className={clsx(styles.container, { [styles.is_shown]: props.is_shown })}>
            <Tooltip
                title={<Title_p />}
                placement="top"
                slotProps={offset}
            >
                <button
                type="button"
                aria-label={t("main_page.message_log.resend_button_label")}
                className={styles.resend_button}
                onPointerDown={startHold}
                onPointerUp={cancelHold}
                onPointerLeave={cancelHold}
                onPointerMove={moveHold}
                onPointerCancel={cancelHold}
                onLostPointerCapture={cancelHold}
                onBlur={cancelHold}
                onClick={onClickFunction}
                >
                    <SendMessageSvg className={styles.send_message_svg} />
                    <RefreshSvg className={styles.refresh_svg} />
                    <div ref={progressRef} className={styles.hold_progress_bar}></div>
                </button>
            </Tooltip>
        </div>
    );
};

const Title_p = () => {
    const { t } = useI18n();
    return <p className={styles.tooltip_title}>{t("main_page.message_log.resend_button_on_hover_desc")}</p>;
};
