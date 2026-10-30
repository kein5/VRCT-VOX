import React from 'react';
import { createRoot } from 'react-dom/client';
import { QuickChat } from '../../../src-ui/views/quick_chat/QuickChat';
import { useMessage } from '../../../src-ui/logics/common/useMessage';
import { store } from '@store';
import '../../../locales/config';
store.backend_subprocess = { write: async line => { window.sent.push(JSON.parse(line)); } };
window.sent = [];
window.quickChatHidden = false;
function App() {
    const { sendMessage } = useMessage();
    const bridge = {
        context: async () => ({ language: 'en', enter_to_send: true, clear_on_send: true }),
        hide: async () => { window.quickChatHidden = true; },
        onOpen: async () => () => {},
        submit: async request => {
            if (window.hold) await new Promise(resolve => { window.release = resolve; });
            if (window.fail) throw new Error('backend_unavailable');
            return sendMessage(request.message, request.id);
        },
    };
    return <QuickChat bridge={bridge} />;
}
createRoot(document.getElementById('root')).render(<App />);
