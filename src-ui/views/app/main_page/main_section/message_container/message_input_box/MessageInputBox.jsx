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
    const history = useRef(null);
    const sending = useRef(false);
    const [pending, setPending] = useState(false);
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

    const onSubmitFunction = async (e) => {
        e.preventDefault();
        if (e.repeat || sending.current) return;

        const message = currentMessageInputValue.data;
        if (!message.trim()) {
            stopTyping();
            updateMessageInputValue("");
            return;
        }

        sending.current = true;
        setPending(true);
        history.current = null;
        if (currentEnableAutoClearMessageInputBox.data) updateMessageInputValue("");

        setTimeout(() => {
            scrollToBottom();
        }, 10);

        try {
            await sendMessage(message);
        } finally {
            sending.current = false;
            setPending(false);
        }
    };

    const onChangeFunction = (e) => {
        const value = e.currentTarget.value;
        history.current = null;
        updateMessageInputValue(value);
        value.trim() ? startTyping() : stopTyping();
    };

    const onKeyDownFunction = (e) => {
        if (e.nativeEvent.isComposing || e.keyCode === 229) return;
        // History is only needed for explicit recall. Incoming captions and
        // translation responses must not subscribe/re-render the composer or
        // rebuild a second copy of the entire sent log after each update.
        if (e.shiftKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
            e.preventDefault();
            const rows = atoms.get(Atom_MessageLogs).data.filter(log => log.category === "sent"
                && typeof log.messages?.original?.message === "string");
            const selection = history.current;
            const index = selection ? rows.findIndex(row => row.id === selection.id) : rows.length;
            // Retention or clearing may remove the selected row between keypresses.
            if (selection && index === -1) {
                updateMessageInputValue(selection.draft);
                history.current = null;
                return;
            }
            const next = index + (e.key === "ArrowUp" ? -1 : 1);
            if (next >= 0 && next < rows.length) {
                history.current = { id: rows[next].id, draft: selection?.draft ?? currentMessageInputValue.data };
                updateMessageInputValue(rows[next].messages.original.message);
            } else if (selection && next >= rows.length) {
                updateMessageInputValue(selection.draft);
                history.current = null;
            }
            return;
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
                <SendMessageButton onSubmitFunction={onSubmitFunction} pending={pending} />
            )}
        </div>
    );
});

const SendMessageButton = ({ onSubmitFunction, pending }) => {
    const { t } = useI18n();
    return (
        <button
            className={styles.message_send_button}
            aria-label={t("studio.send_message")}
            type="button"
            disabled={pending}
            aria-busy={pending}
            onClick={onSubmitFunction}
        >
            <SendMessageSvg aria-hidden="true" className={styles.message_send_icon} />
        </button>
    );
};
