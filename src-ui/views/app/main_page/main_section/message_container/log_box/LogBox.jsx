import { memo, useRef, useState, useLayoutEffect, useEffect, useCallback, useMemo } from "react";
import { useAtomValue } from "jotai";
import { Virtualizer } from "virtua";
import styles from "./LogBox.module.scss";
import { MessageContainer } from "./message_container/MessageContainer";
import { useMessageActions, nextLogView, rowsBetween } from "@logics_common";
import { useSettingValue } from "@logics_configs";
import { useI18n } from "@useI18n";
import { store, Atom_MessageLogs } from "@store";

// Within this many pixels of the end, the log keeps following new rows.
const FOLLOW_THRESHOLD = 5;
// A scroll this soon after wheel, touch or key input counts as the user's.
const USER_SCROLL_MS = 300;
const SCROLL_KEYS = new Set(["PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown", " "]);

// Only the rows in view (plus a margin) are in the DOM, so a full log no longer
// slows down typing, layout or the style recalculation when settings open.
export const LogBox = memo(function LogBox() {
    const { t } = useI18n();
    const followRef = useRef(true);
    const view = useLogView(useAtomValue(Atom_MessageLogs).data, followRef);
    const currentShowResendButton = useSettingValue("ShowResendButton");
    const actions = useMessageActions();
    const logContainerRef = useRef(null);
    const [startMargin, setStartMargin] = useState(0);
    const selection = useSelectedRows();
    const keepMounted = useMemo(() => rowsBetween(view.rows, selection), [view.rows, selection]);

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
        // After a click in the log, PageUp and friends may scroll it with the focus on
        // <body>, so listen on the window. Keys another control handled, keys aimed
        // elsewhere and keys while settings cover the log (inert) are not for it.
        const onKeyDown = (event) => {
            if (!SCROLL_KEYS.has(event.key) || event.defaultPrevented || element.closest("[inert]")
                || !(element.contains(event.target) || event.target === document.body)) return;
            onInput();
            // End scrolls smoothly toward an end that moves while virtua measures
            // the newest rows; go there and follow them as the send button does.
            if (event.key === "End") store.scroll_log_to_bottom();
        };
        const onPointerDown = () => { pointerDown = true; };
        // A short drag can be released before its scroll event arrives.
        const onPointerUp = () => {
            if (pointerDown) onInput();
            pointerDown = false;
        };
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
            [window, "keydown", onKeyDown], [element, "pointerdown", onPointerDown],
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
        // Focusable so the keys keep scrolling it after the clicked row leaves the DOM.
        <div id="log_container" className={styles.container} ref={logContainerRef}
            tabIndex={0} role="region" aria-label={t("main_page.message_log.region_label")}>
            <MessageLogUiSizeController />
            {view.rows.length === 0 && <div className={styles.empty}><h1>{t("studio.empty_title")}</h1><p>{t("studio.empty_description")}</p></div>}
            {/* Rows measured later (new, or after a font size change) call onResize. */}
            <Virtualizer data={view.rows} shift={view.shift} scrollRef={logContainerRef} startMargin={startMargin} onResize={follow}
                keepMounted={keepMounted}>
                {message => message.gone ? <div key={message.id} /> : <MessageContainer key={message.id} {...message}
                    showResendButton={showResendButton} sendMessage={actions?.sendMessage}
                    updateMessageInputValue={actions?.updateMessageInputValue} />}
            </Virtualizer>
        </div>
    );
});

// The rows handed to virtua (see nextLogView). When the oldest rows leave,
// virtua has to see that on its own, so that step is committed before the rest.
// Removed rows stay as empty rows only while the user reads above the end.
const useLogView = (rows, followRef) => {
    const [view, setView] = useState(() => ({ rows, shift: false, source: rows }));
    const next = view.source === rows || view.shift ? view
        : { ...nextLogView(view.rows, rows, !followRef.current), source: rows };
    if (next !== view) setView(next);
    useLayoutEffect(() => {
        if (view.shift) setView({ ...nextLogView(view.rows, view.source, !followRef.current), source: view.source });
    }, [view, followRef]);
    return next;
};

// The rows at both ends of a text selection in the log. The rows between them
// stay mounted, so a selection dragged across several screens keeps its start.
const useSelectedRows = () => {
    const [ends, setEnds] = useState(null);
    useEffect(() => {
        const rowOf = node => (node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement)
            ?.closest("[data-log-row]")?.dataset.logRow;
        const onSelectionChange = () => {
            const selection = document.getSelection();
            const from = selection && !selection.isCollapsed ? rowOf(selection.anchorNode) : undefined;
            const to = from && rowOf(selection.focusNode);
            setEnds(current => !to ? null : current?.from === from && current?.to === to ? current : { from, to });
        };
        document.addEventListener("selectionchange", onSelectionChange);
        return () => document.removeEventListener("selectionchange", onSelectionChange);
    }, []);
    return ends;
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
