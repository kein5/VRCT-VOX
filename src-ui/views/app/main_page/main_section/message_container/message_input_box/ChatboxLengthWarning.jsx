import { memo } from "react";
import { useI18n } from "@useI18n";
import { useStore_MessageInputValue } from "@store";
import { CHATBOX_MAX_LENGTH, chatboxOverflowLength } from "../../../../../../logics/common/chatboxLength";
import styles from "./ChatboxLengthWarning.module.scss";

export const CHATBOX_LENGTH_WARNING_ID = "chatbox_length_warning";

// 入力欄の上 (仕切りとのあいだ) に出す。入力欄の高さは変えず、ログの側が縮む。
// 送信は止めない。読み上げは文が出たときの1回にし、打つたびに変わる文字数は live region の外に置く
export const ChatboxLengthWarning = memo(function ChatboxLengthWarning() {
    const { t } = useI18n();
    const { currentMessageInputValue } = useStore_MessageInputValue();
    const length = chatboxOverflowLength(currentMessageInputValue.data);
    if (length === null) return null;
    return (
        <p id={CHATBOX_LENGTH_WARNING_ID} className={styles.warning}>
            <span role="status">{t("studio.chatbox_too_long", { max: CHATBOX_MAX_LENGTH })}</span>
            <span className={styles.count}>{t("studio.chatbox_length", { length, max: CHATBOX_MAX_LENGTH })}</span>
        </p>
    );
});
