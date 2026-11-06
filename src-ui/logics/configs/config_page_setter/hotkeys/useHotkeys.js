import { useEffect, useRef } from "react";
import { getDefaultStore } from "jotai";
import { store, useStore_Hotkeys, Atom_IsOpenedConfigPage, Atom_IsBackendReady, Atom_IsSoftwareUpdating, Atom_Hotkeys } from "@store";
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
let registrationGeneration = 0;
let registrationOwner = null;
let disposed = false;
// Keep native mutations ordered too: a register already in flight may finish
// after an acknowledgement starts the next reconciliation.
let nativeRegistration = Promise.resolve();
const pendingEdits = new Map();
const reconcileNative = operation => {
    const result = nativeRegistration.then(operation);
    nativeRegistration = result.catch(() => {});
    return result;
};
// Remember that a bind may have reached Rust, even if its UI owner was disposed.
let portalBound = import.meta.hot?.data.portalBound ?? false;
let portalListener = null;
const shortcutsEnabled = () => {
    const atoms = getDefaultStore();
    return atoms.get(Atom_IsBackendReady).data === true &&
        atoms.get(Atom_IsOpenedConfigPage).data === false &&
        atoms.get(Atom_IsSoftwareUpdating).data === false;
};
const pauseShortcuts = () => {
    registrationGeneration++;
    portalPaused = true;
    portalHandler = null;
};
const disposePortalListener = () => {
    pauseShortcuts();
    registrationOwner = null;
    const listener = portalListener;
    portalListener = null;
    listener?.unlisten?.();
};
const ensurePortalListener = () => {
    if (!portalListener) {
        const listener = { unlisten: null, ready: null };
        portalListener = listener;
        listener.ready = listen("portal-shortcut", ({ payload }) => {
            if (portalListener === listener && !portalPaused && shortcutsEnabled() && portalHandler) {
                portalHandler(payload.id, payload.activation_token ?? null);
            }
        }).then(unlisten => {
            if (portalListener !== listener) unlisten();
            else listener.unlisten = unlisten;
        }).catch(error => {
            if (portalListener === listener) portalListener = null;
            throw error;
        });
    }
    return portalListener.ready;
};
if (import.meta.hot) import.meta.hot.dispose(data => {
    data.portalBound = portalBound;
    disposed = true;
    disposePortalListener();
});

export const useHotkeys = () => {
    const owner = useRef({ mounted: true }).current;
    useEffect(() => {
        owner.mounted = true;
        return () => {
            owner.mounted = false;
            if (registrationOwner === owner) disposePortalListener();
        };
    }, [owner]);
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

    const registerPortalShortcuts = async (isCurrent) => {
        await reconcileNative(() => unregisterAll());
        if (!isCurrent()) return;
        portalHandler = runAction;
        const shortcuts = Object.fromEntries(Object.entries(currentHotkeys.data ?? {}).filter(([, keys]) => keys));
        if (!Object.keys(shortcuts).length && !portalBound) {
            portalPaused = false;
            return;
        }
        try {
            await ensurePortalListener();
            if (!isCurrent()) return;
            portalBound = true;
            // The desktop may show its confirmation dialog the first time.
            const assigned = await invoke("portal_shortcuts_bind", { shortcuts });
            if (!isCurrent()) return;
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
            if (!isCurrent()) return;
            const key = `quick_chat.portal_errors.${code}`;
            showNotification_Error(i18n.exists(key) ? t(key) : t("quick_chat.portal_failed", { code: String(code) }),
                { hide_duration: 8000 });
        }
    };

    const setHotkeys = async (hotkeys) => {
        const [targetActionKey, targetHotkey] = Object.entries(hotkeys)[0];
        if (pendingEdits.get(targetActionKey)?.sent) return false;
        const acknowledged = () => getDefaultStore().get(Atom_Hotkeys).data;
        const initial = JSON.stringify(acknowledged()[targetActionKey]);
        const session = store.backend_session;
        const edit = { keys: targetHotkey };
        const isCurrent = () => !disposed && owner.mounted && pendingEdits.get(targetActionKey) === edit &&
            store.backend_session === session && JSON.stringify(acknowledged()[targetActionKey]) === initial;
        const conflict = () => {
            if (!targetHotkey) return false;
            const latest = [...Object.entries(acknowledged()), ...[...pendingEdits].map(([key, value]) => [key, value.keys])];
            return latest.some(([key, keys]) => key !== targetActionKey && keys && parseHotkey(keys) === parseHotkey(targetHotkey));
        };
        const reportConflict = () => {
            showNotification_Error(t("config_page.hotkeys.error_in_use", {
                action_name: getHotkeyActionLabel(targetActionKey, t), hotkey: targetHotkey.join(" + "),
            }));
            return false;
        };
        if (conflict()) return reportConflict();
        // Reserve the proposed content before the first await, across hook instances.
        pendingEdits.set(targetActionKey, edit);
        try {
            if (targetHotkey) {
                const platform = await currentPlatform();
                if (!isCurrent() || (targetActionKey === "open_quick_chat" && !platform)) return false;
                if (conflict()) return reportConflict();
                if (platform !== "wayland") {
                    try {
                        await reconcileNative(async () => {
                            if (!isCurrent()) return;
                            const shortcut = parseHotkey(targetHotkey);
                            await register(shortcut, () => {});
                            await unregister(shortcut);
                        });
                    } catch (error) {
                        if (!isCurrent()) return false;
                        console.warn("Hotkey registration test failed:", error);
                        return reportConflict();
                    }
                }
            }
            if (!isCurrent()) return false;
            if (conflict()) return reportConflict();
            pendingHotkeys();
            closeNotification();
            edit.sent = true;
            const response = await asyncStdoutToPython("/set/data/hotkeys", { [targetActionKey]: targetHotkey });
            return response !== false && (!response?.status || response.status === 200);
        } finally {
            if (pendingEdits.get(targetActionKey) === edit) pendingEdits.delete(targetActionKey);
        }
    };

    const registerShortcuts = async () => {
        pauseShortcuts();
        registrationOwner = owner;
        const generation = registrationGeneration;
        const isCurrent = () => !disposed && owner.mounted && registrationOwner === owner &&
            generation === registrationGeneration && shortcutsEnabled();
        if (!isCurrent()) return;
        const platform = await currentPlatform();
        if (!isCurrent()) return;
        if (platform === "wayland") return registerPortalShortcuts(isCurrent);
        return reconcileNative(async () => {
            if (!isCurrent()) return;
            try {
                await unregisterAll();
                if (!isCurrent()) return;

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
                            if (event.state !== trigger || !isCurrent()) return;
                            await runAction(actionKey);
                        });
                        if (!isCurrent()) return;
                    } catch (error) {
                        if (!isCurrent()) return;
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
                if (!isCurrent()) return;
                console.error("Failed to register global shortcuts:", error);
            }
        });
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
            pauseShortcuts();
            await reconcileNative(() => unregisterAll());
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
        // Older recordings stored Space as " ", which leaves an empty token.
        " ": "Space",
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
