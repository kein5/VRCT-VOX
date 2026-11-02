import { createContext, useContext, useLayoutEffect, useMemo, useRef } from "react";
import { useMessage } from "./useMessage";

const MessageActionsContext = createContext(null);

// Keep the existing send path (including its log retention policy) in one
// place. useMessage currently subscribes to both log and input atoms; isolate
// those subscriptions here so they cannot invalidate either view or its rows.
export const MessageActionsProvider = ({ children }) => {
    const { sendMessage, updateMessageInputValue, startTyping, stopTyping } = useMessage();
    const latest = useRef({ sendMessage, updateMessageInputValue, startTyping, stopTyping });
    useLayoutEffect(() => { latest.current = { sendMessage, updateMessageInputValue, startTyping, stopTyping }; });
    const actions = useMemo(() => ({
        sendMessage: (...args) => latest.current.sendMessage(...args),
        updateMessageInputValue: (...args) => latest.current.updateMessageInputValue(...args),
        startTyping: (...args) => latest.current.startTyping(...args),
        stopTyping: (...args) => latest.current.stopTyping(...args),
    }), []);
    return <MessageActionsContext.Provider value={actions}>{children}</MessageActionsContext.Provider>;
};

// The VR log has no provider: its rows never offer resend/edit actions.
export const useMessageActions = () => useContext(MessageActionsContext);
