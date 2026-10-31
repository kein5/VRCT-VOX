import { store, useStore_Hotkeys } from "@store";
import { useStdoutToPython } from "@useStdoutToPython";
import { useNotificationStatus } from "@logics_common";
import { useMainFunction } from "@logics_main";
import { register, unregister, unregisterAll } from "@tauri-apps/plugin-global-shortcut";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useI18n } from "@useI18n";

// Native Wayland grants no global key grab: the desktop binds the keys
// through the GlobalShortcuts portal and Rust forwards each press here.
let platformRequest = null;
const shortcutPlatform = () => {
    platformRequest ??= invoke("quick_chat_shortcut_platform").catch(error => {
        platformRequest = null;
        throw error;
    });
    return platformRequest;
};
let portalHandler = null;
let portalPaused = true; // Like the plugin's unregisterAll while settings are open.
let portalListener = null;
const ensurePortalListener = () => {
    portalListener ??= listen("portal-shortcut", ({ payload }) => {
        if (!portalPaused && portalHandler) portalHandler(payload.id, payload.activation_token ?? null);
    });
    return portalListener;
};

export const useHotkeys = () => {
    const appWindow = store.appWindow;
    const { t, i18n } = useI18n();

    const { asyncStdoutToPython } = useStdoutToPython();
    const { currentHotkeys, updateHotkeys, pendingHotkeys } = useStore_Hotkeys();
    const {
        toggleTranslation,
        toggleTranscriptionSend,
        toggleTranscriptionReceive,
    } = useMainFunction();

    const getHotkeys = () => {
        pendingHotkeys();
        asyncStdoutToPython("/get/data/hotkeys");
    };
    const { showNotification_SaveSuccess, showNotification_Error, closeNotification } = useNotificationStatus();

    const openQuickChat = async (activationToken = null) => {
        try { await invoke("quick_chat_show", { activationToken }); }
        catch (error) {
            console.warn("Quick chat window could not be focused", error);
            showNotification_Error(t("quick_chat.open_failed"));
        }
    };

    const currentPlatform = async () => {
        try { return await shortcutPlatform(); }
        catch {
            showNotification_Error(t("quick_chat.platform_unknown"));
            return null;
        }
    };

    const runAction = async (actionKey, activationToken = null) => {
        switch (actionKey) {
            case "open_quick_chat": {
                await openQuickChat(activationToken);
                break;
            }
            case "toggle_vrct_visibility": {
                const minimized = await appWindow.isMinimized();
                if (minimized) {
                    await appWindow.unminimize();
                    await appWindow.setFocus();
                    store.text_area_ref.current?.focus();
                } else {
                    await appWindow.minimize();
                }
                break;
            }
            case "toggle_translation": {
                toggleTranslation();
                break;
            }
            case "toggle_transcription_send": {
                toggleTranscriptionSend();
                break;
            }
            case "toggle_transcription_receive": {
                toggleTranscriptionReceive();
                break;
            }
            default: {
                console.warn(`No handler defined for action: ${actionKey}`);
                break;
            }
        }
    };

    const registerPortalShortcuts = async () => {
        await unregisterAll();
        portalHandler = runAction;
        const shortcuts = Object.fromEntries(Object.entries(currentHotkeys.data ?? {}).filter(([, keys]) => keys));
        try {
            await ensurePortalListener();
            // The desktop may show its confirmation dialog the first time.
            const assigned = await invoke("portal_shortcuts_bind", { shortcuts });
            portalPaused = false;
            // The desktop may keep another key, e.g. when VRCT's is taken.
            for (const [actionKey, row] of Object.entries(assigned ?? {})) {
                if (row?.applied !== false) continue;
                showNotification_Error(t("quick_chat.portal_key_kept", {
                    action_name: getHotkeyActionLabel(actionKey, t),
                    wanted: shortcuts[actionKey].join(" + "),
                    hotkey: row.shown || "-",
                }), { hide_duration: 10000 });
            }
        } catch (code) {
            const key = `quick_chat.portal_errors.${code}`;
            showNotification_Error(i18n.exists(key) ? t(key) : t("quick_chat.portal_failed", { code: String(code) }),
                { hide_duration: 8000 });
        }
    };

    const setHotkeys = async (hotkeys) => {
        const [targetActionKey, targetHotkey] = Object.entries(hotkeys)[0];

        // 削除の場合は競合チェックなしで保存
        if (!targetHotkey) {
            pendingHotkeys();
            const updatedHotkeys = { ...currentHotkeys.data, [targetActionKey]: null };
            updateHotkeys(updatedHotkeys);
            asyncStdoutToPython("/set/data/hotkeys", updatedHotkeys);
            closeNotification();
            return true;
        }

        const platform = await currentPlatform();
        if (targetActionKey === "open_quick_chat" && !platform) return false;

        const targetShortcut = parseHotkey(targetHotkey);
        const targetDisplay = targetHotkey.join(" + ");
        const actionLabel = getHotkeyActionLabel(targetActionKey, t);

        // 1. VRCT内の他のホットキーと重複していないかチェック
        for (const [actionKey, hotkey] of Object.entries(currentHotkeys.data)) {
            if (actionKey === targetActionKey || !hotkey) continue;
            const shortcut = parseHotkey(hotkey);
            if (shortcut === targetShortcut) {
                showNotification_Error(
                    t("config_page.hotkeys.error_in_use", {
                        action_name: actionLabel,
                        hotkey: targetDisplay,
                    })
                );
                return false;
            }
        }

        // 2. OS / 他のアプリケーションで既に使用されていないか（テスト登録）
        // On native Wayland the desktop resolves conflicts when binding.
        let isOsConflict = false;
        if (platform !== "wayland") {
            try {
                await register(targetShortcut, () => {});
                await unregister(targetShortcut);
            } catch (err) {
                console.warn(`Hotkey registration test failed for ${targetShortcut}:`, err);
                isOsConflict = true;
            }
        }

        if (isOsConflict) {
            showNotification_Error(
                t("config_page.hotkeys.error_in_use", {
                    action_name: actionLabel,
                    hotkey: targetDisplay,
                })
            );
            return false;
        }

        // 3. 競合なし：保存してバックエンドに送信
        pendingHotkeys();
        const updatedHotkeys = { ...currentHotkeys.data, [targetActionKey]: targetHotkey };
        updateHotkeys(updatedHotkeys);
        asyncStdoutToPython("/set/data/hotkeys", updatedHotkeys);
        closeNotification();
        return true;
    };

    const registerShortcuts = async () => {
        if (await currentPlatform() === "wayland") return registerPortalShortcuts();
        try {
            await unregisterAll();

            const hotkeyEntries = Object.entries(currentHotkeys.data);
            const failedHotkeys = [];

            for (const [actionKey, hotkeyRaw] of hotkeyEntries) {
                if (!hotkeyRaw) continue;

                const shortcut = parseHotkey(hotkeyRaw);
                try {
                    await register(shortcut, async (event) => {
                        // Moving focus during an X11 key grab can lose its release
                        // event and leave the shortcut stuck in the pressed state.
                        const trigger = actionKey === "open_quick_chat" ? "Released" : "Pressed";
                        if (event.state !== trigger) return;
                        await runAction(actionKey);
                    });
                } catch (error) {
                    console.warn(`Failed to register global shortcut ${shortcut} for ${actionKey}:`, error);
                    failedHotkeys.push({
                        actionKey,
                        hotkey: hotkeyRaw.join(" + "),
                    });
                }
            }

            if (failedHotkeys.length > 0) {
                // 起動時 / 有効化時に他アプリで使用されていて登録できなかったホットキーを通知（設定は削除しない）
                failedHotkeys.forEach(({ actionKey, hotkey }) => {
                    const actionLabel = getHotkeyActionLabel(actionKey, t);
                    showNotification_Error(
                        t("config_page.hotkeys.error_failed_to_register_at_launch", {
                            action_name: actionLabel,
                            hotkey,
                        }),
                        { hide_duration: 8000 }
                    );
                });
            }
        } catch (error) {
            console.error("Failed to register global shortcuts:", error);
        }
    };

    const setSuccessHotkeys = (hotkeys) => {
        updateHotkeys(hotkeys);
        showNotification_SaveSuccess();
    };

    return {
        currentHotkeys,
        getHotkeys,
        updateHotkeys,
        setHotkeys,
        setSuccessHotkeys,
        registerShortcuts,
        unregisterAll: async () => {
            portalPaused = true;
            await unregisterAll();
        },
        openQuickChat,
    };
};

// 修飾キーのパースを行う関数
const parseHotkey = (hotkeyString) => {
    const keyMap = {
        Ctrl: "Control",
        Alt: "Alt",
        Shift: "Shift",
        Meta: "Super",
    };


    return hotkeyString
        .map((key) => keyMap[key] || key)
        .join("+");
};

// アクション名（多言語対応）を取得する関数
const getHotkeyActionLabel = (actionKey, t) => {
    switch (actionKey) {
        case "open_quick_chat":
            return t("quick_chat.label");
        case "toggle_vrct_visibility":
            return t("config_page.hotkeys.toggle_vrct_visibility.label");
        case "toggle_translation":
            return t("config_page.hotkeys.toggle_translation.label", {
                translation: t("main_page.translation"),
            });
        case "toggle_transcription_send":
            return t("config_page.hotkeys.toggle_transcription_send.label", {
                transcription_send: t("main_page.transcription_send"),
            });
        case "toggle_transcription_receive":
            return t("config_page.hotkeys.toggle_transcription_receive.label", {
                transcription_receive: t("main_page.transcription_receive"),
            });
        default:
            return actionKey;
    }
};
