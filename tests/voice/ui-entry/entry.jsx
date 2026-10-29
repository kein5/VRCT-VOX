// Test assembly only: the input, settings, hooks and response routes are production imports.
import React, { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { store, useStore_MessageLogs } from "@store";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { MessageInputBox } from "../../../src-ui/views/app/main_page/main_section/message_container/message_input_box/MessageInputBox";
import { DirectVoiceSettings } from "../../../src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/DirectVoiceSettings";
import { VoiceRouteSettings } from "../../../src-ui/views/app/config_page/setting_section/setting_box/device/VoiceRouteSettings";
import { MainFunctionSwitch } from "../../../src-ui/views/app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch";
import { VoiceSettings } from "../../../src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/VoiceSettings";
import { useVoice } from "../../../src-ui/logics/voice/useVoice";
import "../../../locales/config";

store.log_box_ref = { current: null };
store.backend_subprocess = { write: line => window.sidecarWrite(line) };
window.entry = { received: [], sent: [], errors: [] };

function App() {
    const { receiveRoutes } = useReceiveRoutes();
    const { settings, status, route, error } = useVoice();
    const { currentMessageLogs } = useStore_MessageLogs();
    const receiver = useRef(receiveRoutes);
    receiver.current = receiveRoutes;
    window.entry.state = { settings, status, route, error, logs: currentMessageLogs.data };
    useEffect(() => {
        let active = true;
        const poll = async () => {
            try {
                for (const line of await window.sidecarRead()) {
                    const response = JSON.parse(line);
                    if (response.status === 348) continue;
                    window.entry.received.push(response);
                    if (!response.endpoint.startsWith("/__test__/")) receiver.current(response);
                }
            } catch (e) { window.entry.errors.push(String(e)); }
            if (active) setTimeout(poll, 20);
        };
        poll();
        return () => { active = false; };
    }, []);
    return <main style={{ maxWidth: 900, margin: "24px auto", color: "#222", background: "#fff" }}>
        <p>Integration fixture — production VRCT components; substituted desktop transport and inactive services.</p>
        <div data-testid="chat" style={{ height: 110 }}><MessageInputBox /></div>
        <MainFunctionSwitch /><VoiceRouteSettings /><VoiceSettings /><DirectVoiceSettings />
        <pre data-testid="message-log">{JSON.stringify(currentMessageLogs.data, null, 2)}</pre>
    </main>;
}
createRoot(document.getElementById("root")).render(<App />);
