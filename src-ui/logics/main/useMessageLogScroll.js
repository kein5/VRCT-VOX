import { useCallback } from "react";
import { store } from "@store";

// Jump to the newest row, e.g. after sending while scrolled up, and keep
// following new rows from there (LogBox).
export const useMessageLogScroll = () => {
    const scrollToBottom = useCallback(() => store.scroll_log_to_bottom?.(), []);
    return { scrollToBottom };
};
