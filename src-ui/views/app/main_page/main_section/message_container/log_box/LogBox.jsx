import { memo, useRef, useState, useLayoutEffect, useEffect, useCallback } from "react";
import { useAtomValue } from "jotai";
import { Virtualizer } from "virtua";
import styles from "./LogBox.module.scss";
import { MessageContainer } from "./message_container/MessageContainer";
import { useMessageActions, nextLogView } from "@logics_common";
import { useSettingValue } from "@logics_configs";
import { useI18n } from "@useI18n";
import { store, Atom_MessageLogs } from "@store";

// Within this many pixels of the end, the log keeps following new rows.
const FOLLOW_THRESHOLD = 5;
// A scroll this soon after wheel, touch or key input counts as the user's.
const USER_SCROLL_MS = 300;

// Only the rows in view (plus a margin) are in the DOM, so a full log no longer
// slows down typing, layout or the style recalculation when settings open.
export const LogBox = memo(function LogBox() {
    const { t } = useI18n();
    const view = useLogView(useAtomValue(Atom_MessageLogs).data);
    const currentShowResendButton = useSettingValue("ShowResendButton");
    const actions = useMessageActions();
    const logContainerRef = useRef(null);
    const followRef = useRef(true);
    const [startMargin, setStartMargin] = useState(0);

    const follow = useCallback(() => {
        const element = logContainerRef.current;
        if (element && followRef.current) element.scrollTop = element.scrollHeight;
    }, []);

    useLayoutEffect(() => {
        const element = logContainerRef.current;
        if (!element) return;
        store.scroll_log_to_bottom = () => {
            followRef.current = true;
            follow();
        };
        let userUntil = 0, pointerDown = false;
        const onInput = () => { userUntil = performance.now() + USER_SCROLL_MS; };
        const onPointerDown = () => { pointerDown = true; };
        const onPointerUp = () => { pointerDown = false; };
        // Only the user (wheel, touch, keys, dragging the scrollbar or a selection)
        // stops the following. Scrolls caused by layout, such as rows being measured
        // or a resize, go back to the end instead.
        const onScroll = () => {
            const atEnd = element.scrollHeight - element.scrollTop - element.clientHeight < FOLLOW_THRESHOLD;
            if (pointerDown || performance.now() < userUntil) followRef.current = atEnd;
            else if (atEnd) followRef.current = true;
            else follow();
        };
        // The padding before the rows is in rem, so it changes with the UI scale.
        const observer = new ResizeObserver(() => {
            setStartMargin(parseFloat(getComputedStyle(element).paddingTop) || 0);
            follow();
        });
        const listeners = [[element, "scroll", onScroll], [element, "wheel", onInput], [element, "touchmove", onInput],
            [element, "keydown", onInput], [element, "pointerdown", onPointerDown],
            [window, "pointerup", onPointerUp], [window, "pointercancel", onPointerUp]];
        listeners.forEach(([target, type, listener]) => target.addEventListener(type, listener, { passive: true }));
        observer.observe(element);
        return () => {
            listeners.forEach(([target, type, listener]) => target.removeEventListener(type, listener));
            observer.disconnect();
            store.scroll_log_to_bottom = null;
        };
    }, [follow]);

    useLayoutEffect(() => follow(), [view, follow]);

    const showResendButton = !!actions && currentShowResendButton.data;
    return (
        <div id="log_container" className={styles.container} ref={logContainerRef}>
            <MessageLogUiSizeController />
            {view.rows.length === 0 && <div className={styles.empty}><h1>{t("studio.empty_title")}</h1><p>{t("studio.empty_description")}</p></div>}
            {/* Rows measured later (new, or after a font size change) call onResize. */}
            <Virtualizer data={view.rows} shift={view.shift} scrollRef={logContainerRef} startMargin={startMargin} onResize={follow}>
                {message => <MessageContainer key={message.id} {...message} showResendButton={showResendButton}
                    sendMessage={actions?.sendMessage} updateMessageInputValue={actions?.updateMessageInputValue} />}
            </Virtualizer>
        </div>
    );
});

// When the oldest rows leave, virtua has to see that change on its own (see
// nextLogView), so that step is committed before the rest of the update.
const useLogView = (rows) => {
    const [view, setView] = useState(() => ({ rows, shift: false }));
    const next = view.rows === rows || view.shift ? view : nextLogView(view.rows, rows);
    if (next !== view) setView(next);
    useLayoutEffect(() => {
        if (view.shift) setView({ rows, shift: false });
    }, [view, rows]);
    return next;
};

const MessageLogUiSizeController = memo(function MessageLogUiSizeController() {
    const currentMessageLogUiScaling = useSettingValue("MessageLogUiScaling");
    const font_size = currentMessageLogUiScaling.data / 100;

    useEffect(() => {
        const log_container_el = document.getElementById("log_container");
        log_container_el.style.setProperty("font-size", `${font_size}rem`);
    }, [currentMessageLogUiScaling.data]);

    return null;
});
