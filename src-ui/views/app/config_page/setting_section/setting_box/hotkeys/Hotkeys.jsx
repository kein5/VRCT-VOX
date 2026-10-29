import { useHotkeys } from "@logics_configs";
import styles from "./Hotkeys.module.scss";
import { HotkeysEntryContainer } from "../_templates/Templates";
import { useI18n } from "@useI18n";
import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useIsOpenedConfigPage } from "@logics_common";
export const Hotkeys = () => {
    const { t } = useI18n();
    return (
        <div className={styles.container}>
            <p className={styles.disabled_notice}>{t("config_page.hotkeys.disabled_notice")}</p>
            <HotkeysBoxContainer />
        </div>
    );
};

const HotkeysBoxContainer = () => {
    const { t } = useI18n();
    const { currentHotkeys, setHotkeys, openQuickChat } = useHotkeys();
    const { setIsOpenedConfigPage } = useIsOpenedConfigPage();
    const [platform, setPlatform] = useState(null);
    useEffect(() => {
        invoke("quick_chat_shortcut_platform").then(setPlatform).catch(() => setPlatform("unknown"));
    }, []);

    return (
        <div className={styles.container}>
            <HotkeysEntryContainer
                label={t("quick_chat.label")}
                hotkey_id="open_quick_chat"
                value={currentHotkeys.data}
                state={currentHotkeys.state}
                setHotkeys={setHotkeys}
            />
            <p className={styles.quick_chat_notice}>{t("quick_chat.shortcut_hint")}</p>
            {platform === "wayland" && <p role="status" className={styles.quick_chat_notice}>{t("quick_chat.wayland_unavailable")}</p>}
            {platform === "xwayland" && <p role="status" className={styles.quick_chat_notice}>{t("quick_chat.xwayland_hint")}</p>}
            {platform === "unknown" && <p role="status" className={styles.quick_chat_notice}>{t("quick_chat.platform_unknown")}</p>}
            <button type="button" className={styles.open_quick_chat} onClick={() => { setIsOpenedConfigPage(false); openQuickChat(); }}>
                {t("quick_chat.open")}
            </button>
            <HotkeysEntryContainer
                label={t("config_page.hotkeys.toggle_vrct_visibility.label")}
                hotkey_id="toggle_vrct_visibility"
                value={currentHotkeys.data}
                state={currentHotkeys.state}
                setHotkeys={setHotkeys}
            />
            <HotkeysEntryContainer
                label={t("config_page.hotkeys.toggle_translation.label", {translation: t("main_page.translation")})}
                hotkey_id="toggle_translation"
                value={currentHotkeys.data}
                state={currentHotkeys.state}
                setHotkeys={setHotkeys}
            />
            <HotkeysEntryContainer
                label={t("config_page.hotkeys.toggle_transcription_send.label", {transcription_send: t("main_page.transcription_send")})}
                hotkey_id="toggle_transcription_send"
                value={currentHotkeys.data}
                state={currentHotkeys.state}
                setHotkeys={setHotkeys}
            />
            <HotkeysEntryContainer
                label={t("config_page.hotkeys.toggle_transcription_receive.label", {transcription_receive: t("main_page.transcription_receive")})}
                hotkey_id="toggle_transcription_receive"
                value={currentHotkeys.data}
                state={currentHotkeys.state}
                setHotkeys={setHotkeys}
            />
        </div>
    );
};
