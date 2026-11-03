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
const EDITABLE = "input, textarea, select, [contenteditable]";

// Only the rows in view (plus a margin) are in the DOM, so a full log no longer
// slows down typing, layout or the style recalculation when settings open.
export const LogBox = memo(function LogBox() {
    const { t } = useI18n();
    const view = useLogView(useAtomValue(Atom_MessageLogs).data);
    const currentShowResendButton = useSettingValue("ShowResendButton");
    const actions = useMessageActions();
    const logContainerRef = useRef(null);
    const followRef = useRef(true);
    const anchorRef = useRef(null);
    const [startMargin, setStartMargin] = useState(0);
    const selection = useSelectedRows();
    const keepMounted = useMemo(() => rowsBetween(view.rows, selection), [view.rows, selection]);

    // Stay at the end while following; otherwise remember the row being read.
    const follow = useCallback(() => {
        const element = logContainerRef.current;
        if (!element) return;
        if (followRef.current) element.scrollTop = element.scrollHeight;
        else anchorRef.current = readAnchor(element);
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
        // After a click in the log, PageUp and friends scroll it with the focus on
        // <body>, so listen on the window; keys typed into a field do not scroll it.
        const onKeyDown = (event) => {
            if (SCROLL_KEYS.has(event.key) && !event.target.closest?.(EDITABLE)) onInput();
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
            follow();
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

    // virtua sizes rows by their index, so removing a row in the middle (a
    // discarded caption) moves the rows after it. Put the row being read back.
    useLayoutEffect(() => {
        const element = logContainerRef.current, anchor = anchorRef.current;
        if (element && anchor && !followRef.current) {
            const row = element.querySelector(`[data-log-row="${CSS.escape(anchor.id)}"]`);
            if (row) element.scrollTop += row.getBoundingClientRect().top - element.getBoundingClientRect().top - anchor.offset;
        }
        follow();
    }, [view, follow]);

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

// The first row in view and how far its top is from the top of the log.
const readAnchor = (element) => {
    const top = element.getBoundingClientRect().top;
    for (const row of element.querySelectorAll("[data-log-row]")) {
        const rect = row.getBoundingClientRect();
        if (rect.bottom > top) return { id: row.dataset.logRow, offset: rect.top - top };
    }
    return null;
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
