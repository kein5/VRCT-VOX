import { useEffect, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { useI18n } from '@useI18n';
import { useMessage } from '../../../logics/common/useMessage';
import { useIsBackendReady, useIsOpenedConfigPage, useIsSoftwareUpdating } from '@logics_common';
import { useAppearance, useOthers } from '@logics_configs';

export const QuickChatController = () => {
    const { sendMessage } = useMessage();
    const { i18n } = useI18n();
    const { currentIsBackendReady } = useIsBackendReady();
    const { currentIsSoftwareUpdating } = useIsSoftwareUpdating();
    const { currentIsOpenedConfigPage } = useIsOpenedConfigPage();
    const { currentSendMessageButtonType } = useAppearance();
    const { currentEnableAutoClearMessageInputBox } = useOthers();
    const ready = currentIsBackendReady.data && !currentIsSoftwareUpdating.data && !currentIsOpenedConfigPage.data;
    const current = useRef();
    current.current = { ready, sendMessage };
    useEffect(() => {
        const receive = async () => {
            try {
                // Notification payloads are ignored. Only native, label-validated requests can be taken.
                const request = await invoke('quick_chat_take');
                if (!request) return;
                let accepted = false;
                try { if (current.current.ready) accepted = await current.current.sendMessage(request.message, request.id); }
                finally { await invoke('quick_chat_finish', { id: request.id, accepted: accepted === true }); }
            } catch (error) { console.error('Quick chat handoff failed', error); }
        };
        const listener = listen('quick-chat-requested', receive);
        listener.then(receive);
        return () => { listener.then(off => off()); };
    }, []);
    useEffect(() => {
        invoke('quick_chat_configure', { context: { ready: !!ready, language: i18n.language,
            enter_to_send: currentSendMessageButtonType.data !== 'show_and_disable_enter_key',
            clear_on_send: !!currentEnableAutoClearMessageInputBox.data } }).catch(console.error);
    }, [ready, i18n.language, currentSendMessageButtonType.data, currentEnableAutoClearMessageInputBox.data]);
    return null;
};
