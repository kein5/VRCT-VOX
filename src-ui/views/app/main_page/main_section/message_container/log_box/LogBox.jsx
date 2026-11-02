import { memo, useRef, useLayoutEffect, useEffect } from "react";
import { useAtomValue } from "jotai";
import styles from "./LogBox.module.scss";
import { MessageContainer } from "./message_container/MessageContainer";
import { useMessageActions } from "@logics_common";
import { useSettingValue } from "@logics_configs";
import { useMessageLogScroll } from "@logics_main";
import { useI18n } from "@useI18n";
import { store, Atom_MessageLogs } from "@store";

export const LogBox = memo(function LogBox() {
    const { t } = useI18n();
    const currentMessageLogs = useAtomValue(Atom_MessageLogs);
    const currentShowResendButton = useSettingValue("ShowResendButton");
    const actions = useMessageActions();
    const { scrollToBottom, isScrolling } = useMessageLogScroll();
    const logContainerRef = useRef(null);

    useLayoutEffect(() => {
        store.log_box_ref = logContainerRef;
        if (!isScrolling) {
            scrollToBottom();
        }
    }, [currentMessageLogs.data, isScrolling]);

    return (
        <div id="log_container" className={styles.container} ref={logContainerRef}>
            <MessageLogUiSizeController />
            {currentMessageLogs.data.length === 0 && <div className={styles.empty}><h1>{t("studio.empty_title")}</h1><p>{t("studio.empty_description")}</p></div>}
            <MessageRows messages={currentMessageLogs.data} showResendButton={!!actions && currentShowResendButton.data}
                sendMessage={actions?.sendMessage} updateMessageInputValue={actions?.updateMessageInputValue} />
        </div>
    );
});

// Keep even the list traversal out of composer-only updates. Individual rows
// retain their object references when another message is added or confirmed.
const MessageRows = memo(function MessageRows({ messages, ...props }) {
    return messages.map(message => <MessageContainer key={message.id} {...message} {...props} />);
});

const MessageLogUiSizeController = memo(function MessageLogUiSizeController() {
    const currentMessageLogUiScaling = useSettingValue("MessageLogUiScaling");
    const font_size = currentMessageLogUiScaling.data / 100;

    useEffect(() => {
        const log_container_el = document.getElementById("log_container");
        log_container_el.style.setProperty("font-size", `${font_size}rem`);
    }, [currentMessageLogUiScaling.data]);

    return null;
});
