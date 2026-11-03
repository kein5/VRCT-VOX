import { memo, useState, useEffect, useLayoutEffect, useRef } from "react";
import { useStore } from "jotai";
import styles from "./MessageInputBox.module.scss";
import SendMessageSvg from "@images/send_message.svg?react";
import { useMessageActions } from "@logics_common";
import { useSettingValue } from "@logics_configs";
import { useMessageLogScroll } from "@logics_main";
import { useI18n } from "@useI18n";
import { store, Atom_MessageLogs, useStore_MessageInputValue } from "@store";
import { chatboxOverflowLength } from "../../../../../../logics/common/chatboxLength";
import { CHATBOX_LENGTH_WARNING_ID } from "./ChatboxLengthWarning";

export const MessageInputBox = memo(function MessageInputBox() {
    const { t } = useI18n();
    const [history_index, setHistoryIndex] = useState(-1);
    const atoms = useStore();
    const { currentMessageInputValue, updateMessageInputValue } = useStore_MessageInputValue();
    const { sendMessage, startTyping, stopTyping } = useMessageActions();

    const currentEnableAutoClearMessageInputBox = useSettingValue("EnableAutoClearMessageInputBox");
    const currentSendMessageButtonType = useSettingValue("SendMessageButtonType");

    const { scrollToBottom } = useMessageLogScroll();

    const log_box_ref = useRef(null);

    useLayoutEffect(() => {
        store.text_area_ref = log_box_ref;
    }, []);

    useEffect(() => {
        // Auto-clear and history recall also change the value without onChange.
        if (!currentMessageInputValue.data.trim()) stopTyping();
    }, [currentMessageInputValue.data, stopTyping]);

    const onSubmitFunction = (e) => {
        e.preventDefault();

        sendMessage(currentMessageInputValue.data);

        if (!currentMessageInputValue.data.trim()) return updateMessageInputValue("");

        if (currentEnableAutoClearMessageInputBox.data) updateMessageInputValue("");

        setTimeout(() => {
            scrollToBottom();
        }, 10);

        setHistoryIndex(-1);
    };

    const onChangeFunction = (e) => {
        const value = e.currentTarget.value;
        updateMessageInputValue(value);
        value.trim() ? startTyping() : stopTyping();
    };

    const onKeyDownFunction = (e) => {
        if (e.nativeEvent.isComposing || e.keyCode === 229) return;
        // History is only needed for explicit recall. Incoming captions and
        // translation responses must not subscribe/re-render the composer or
        // rebuild a second copy of the entire sent log after each update.
        const message_history = e.shiftKey && (e.key === "ArrowUp" || e.key === "ArrowDown")
            ? atoms.get(Atom_MessageLogs).data.filter(log => log.category === "sent")
                .map(log => log.messages.original.message)
            : [];
        if (e.key === "ArrowUp" && e.shiftKey) {
            e.preventDefault();

            if (history_index + 1 < message_history.length) {
                const new_index = history_index + 1;
                setHistoryIndex(new_index);
                updateMessageInputValue(message_history[message_history.length - 1 - new_index]);
            }
        }

        if (e.key === "ArrowDown" && e.shiftKey) {
            e.preventDefault();

            if (history_index > -1) {
                const new_index = history_index - 1;
                setHistoryIndex(new_index);
                updateMessageInputValue(
                    new_index >= 0
                        ? message_history[message_history.length - 1 - new_index]
                        : ""
                );
            }
        }

        if (currentSendMessageButtonType.data === "show_and_disable_enter_key") return;

        if (e.keyCode === 13 && !e.shiftKey) {
            onSubmitFunction(e);
        }

    };

    return (
        <div className={styles.container}>
            <div className={styles.message_box_wrapper}>
                <textarea
                    ref={log_box_ref}
                    className={styles.message_box_input_area}
                    onChange={onChangeFunction}
                    onBlur={stopTyping}
                    aria-label={t("studio.message_input")}
                    aria-describedby={chatboxOverflowLength(currentMessageInputValue.data) !== null ? CHATBOX_LENGTH_WARNING_ID : undefined}
                    placeholder={t("studio.message_placeholder")}
                    value={currentMessageInputValue.data}
                    onKeyDown={onKeyDownFunction}
                />
            </div>
            {currentSendMessageButtonType.data !== "hide" && (
                <SendMessageButton onSubmitFunction={onSubmitFunction} />
            )}
        </div>
    );
});

const SendMessageButton = ({ onSubmitFunction }) => {
    const { t } = useI18n();
    return (
        <button
            className={styles.message_send_button}
            aria-label={t("studio.send_message")}
            type="button"
            onClick={onSubmitFunction}
        >
            <SendMessageSvg aria-hidden="true" className={styles.message_send_icon} />
        </button>
    );
};
