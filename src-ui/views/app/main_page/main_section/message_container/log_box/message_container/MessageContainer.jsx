import { memo, useState } from "react";
import { useI18n } from "@useI18n";
import clsx from "clsx";
import styles from "./MessageContainer.module.scss";
import { MessageSubMenuContainer } from "./message_sub_menu_container/MessageSubMenuContainer";
import { store } from "@store";

export const MessageContainer = memo(function MessageContainer({ id, messages, status, category, created_at, source, realtime, delivery_reason,
    speakers, sendMessage, updateMessageInputValue, showResendButton }) {
    const { t } = useI18n();
    const [is_hovered, setIsHovered] = useState(false);
    const [is_locked, setIsLocked] = useState(false);

    const resendFunction = () => {
        sendMessage(messages.original.message);
    };
    const editFunction = () => {
        updateMessageInputValue(messages.original.message);
    };

    const handleMouseEnter = () => {
        if (!is_locked) {
            setIsHovered(true);
        }
    };

    const handleMouseLeave = () => {
        setIsHovered(false);
        setIsLocked(false);
    };

    const lockHoverState = () => {
        setIsHovered(false);
        setIsLocked(true);
    };

    const is_translation_exist = messages.translations?.length > 0;
    const is_pending = status === "pending";
    const is_failed = status === "failed";
    const is_not_sent = status === "not_sent";
    const is_sent_message = category === "sent";
    const is_system_message = category === "system";
    const is_ocr_message = source === "ocr";
    const is_realtime = source === "realtime_mic" || source === "realtime_speaker";
    // The message reached the log and the other outputs, but the chatbox is switched off.
    const is_vrchat_off = is_sent_message && status === "ok" && (realtime?.reason ?? delivery_reason) === "vrchat_off";
    const not_sent_key = ["expired", "revoked", "superseded", "filtered"].includes(realtime?.reason)
        ? `not_sent_${realtime.reason}` : "not_sent";
    const category_text = is_realtime && is_not_sent
        ? t(`main_page.message_log.${is_sent_message ? not_sent_key : "processing_stopped"}`)
        : is_realtime && is_failed
        ? t(`main_page.message_log.${is_sent_message ? "send_unconfirmed" : "processing_failed"}`)
        : is_realtime && is_pending && !is_sent_message
        ? t("main_page.message_log.processing")
        : is_sent_message
        ? t(`main_page.message_log.${is_failed ? "send_unconfirmed" : is_pending ? "sending" : is_vrchat_off ? "sent_vrchat_off" : "sent"}`)
        : is_system_message
        ? t("main_page.message_log.system")
        : is_ocr_message
        ? t("main_page.message_log.received_ocr", { ocr: t("main_page.ocr") })
        : t("main_page.message_log.received");
    // Who spoke, where the server told the voices apart: "A", or "A・B" when two share a caption.
    const speakers_text = !is_sent_message && speakers?.length
        ? t("main_page.message_log.speakers", { speakers: speakers.join(t("main_page.message_log.speakers_separator")) })
        : null;

    const message_type_class_name = clsx({
        [styles.sent_message]: is_sent_message,
        [styles.received_message]: !is_sent_message && !is_system_message,
        [styles.system_message]: is_system_message,
    });

    return (
        <div
            data-log-row={id}
            className={clsx(styles.container, message_type_class_name)}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        >
            <div className={clsx(styles.message_wrapper, message_type_class_name)}>
                <div className={clsx(styles.info_box, message_type_class_name)}>
                    <p className={styles.time}>{created_at}</p>
                    <p className={clsx(styles.category, message_type_class_name, {
                        [styles.ocr_category]: is_ocr_message, [styles.failed]: is_failed,
                        [styles.not_sent]: is_not_sent, [styles.vrchat_off]: is_vrchat_off,
                    })}>{category_text}</p>
                    {speakers_text && <p className={clsx(styles.category, message_type_class_name)}>{speakers_text}</p>}
                    {/* The VR atlas needs static pixels while a send is pending. Its label above shows the state. */}
                    {(is_sent_message || is_realtime) && is_pending && !store.is_vr_panel && <span className={styles.loader} aria-hidden="true"></span>}
                </div>
                <div className={clsx(styles.message_box, message_type_class_name)}>
                    {is_system_message ? (
                        <p className={styles.message_main_system}>{messages.original.message}</p>
                    ) : is_translation_exist ? (
                        <WithTranslatedMessages messages={messages} />
                    ) : (
                        <OriginalMessage messages={messages} />
                    )}
                </div>
            </div>
            {/* VRパネルでは、レーザーの誤操作で過去のメッセージを再送しないよう出さない */}
            {/* Rendered whenever enabled so the keyboard can reach it; shown on hover or focus. */}
            {showResendButton && is_sent_message && !store.is_vr_panel ? (
                <MessageSubMenuContainer
                    is_shown={is_hovered}
                    setIsHovered={lockHoverState}
                    resendFunction={resendFunction}
                    editFunction={editFunction}
                />
            ) : null}
        </div>
    );
});

const MessageWithTransliteration = ({ item }) => {
    const renderTokenNode = (token, key) => {
        const orig = token.orig ?? "";
        const hira = token.hira ?? "";
        const hepburn = token.hepburn ?? "";

        // Only hovered romaji if it exists. (No ruby cuz 'orig' and 'hira' are same.)
        if (hira && hira === orig && hepburn) {
            return (
                <span key={key} title={hepburn} className={styles.with_hepburn}>
                    {orig}
                </span>
            );
        }

        // Ruby hiragana and hovered romaji.
        if (hira && hepburn) {
            return (
                <ruby key={key} title={hepburn} className={styles.with_hepburn}>
                    {orig}
                    <rt>{hira}</rt>
                </ruby>
            );
        }

        // Ruby romaji or hiragana.
        if (hepburn || hira) {
            const ruby = hepburn ? hepburn : hira;
            if (ruby !== orig) {
                return (
                    <ruby key={key} className={styles.ruby}>
                        {orig}
                        <rt>{ruby}</rt>
                    </ruby>
                );
            };
        }

        // Nothing. Original only.
        return (
            <span key={key} className={styles.original_only}>
                {orig}
            </span>
        );
    };

    if (!item.transliteration.length) {
        return <p className={styles.message_main}>{item.message}</p>;
    }

    return (
        <p className={styles.message_main}>
            {item.transliteration.map((token, idx) => renderTokenNode(token, idx))}
        </p>
    );
};

const OriginalMessage = ({ messages }) => {
    return (
        <>
            <MessageWithTransliteration item={messages.original} />
        </>
    );
};

const WithTranslatedMessages = ({ messages }) => {
    return (
        <>
            <p className={styles.message_second}>{messages.original.message}</p>
            {messages.translations.map((item, idx) => (
                <div key={idx}>
                    <MessageWithTransliteration item={item} />
                </div>
            ))}
        </>
    );
};
