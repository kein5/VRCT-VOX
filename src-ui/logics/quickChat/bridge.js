import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

export const quickChatBridge = {
    context: () => invoke('quick_chat_context'),
    hide: () => invoke('quick_chat_hide'),
    onOpen: callback => listen('quick-chat-opened', callback),
    submit: async request => {
        let finish;
        const result = new Promise(resolve => { finish = resolve; });
        const unlisten = await listen('quick-chat-result', ({ payload }) => {
            if (payload.id === request.id) finish(payload.accepted);
        });
        try {
            const replay = await invoke('quick_chat_submit', { request });
            return replay ? replay.accepted : await result;
        } finally { unlisten(); }
    },
};
