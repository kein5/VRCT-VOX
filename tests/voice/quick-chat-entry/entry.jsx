import React from 'react';
import { createRoot } from 'react-dom/client';
import { QuickChat } from '../../../src-ui/views/quick_chat/QuickChat';
import { useMessage } from '../../../src-ui/logics/common/useMessage';
import { store } from '@store';
import '../../../locales/config';
store.backend_subprocess = { write: async line => { window.sent.push(JSON.parse(line)); } };
window.sent = [];
window.quickChatHidden = false;
let sendMessage;
// One object for the whole page, like quickChatBridge. QuickChat subscribes again
// and reads the context when its bridge changes, and useMessage re-renders App on
// every language change: a bridge made in App never stops changing.
const bridge = {
    context: async () => ({ language: 'en', enter_to_send: true, clear_on_send: true }),
    hide: async () => { window.quickChatHidden = true; },
    onOpen: async () => () => {},
    onContextChanged: async () => () => {},
    growBy: async () => {},
    submit: async request => {
        if (window.hold) await new Promise(resolve => { window.release = resolve; });
        if (window.fail) throw new Error('backend_unavailable');
        return sendMessage(request.message, request.id);
    },
};
function App() {
    ({ sendMessage } = useMessage());
    return <QuickChat bridge={bridge} />;
}
createRoot(document.getElementById('root')).render(<App />);
