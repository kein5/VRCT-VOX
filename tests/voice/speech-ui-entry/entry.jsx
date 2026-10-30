// Production components and response routes; only the desktop transport is replaced.
import React, { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { store } from "@store";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { SpeechServers } from "../../../src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/SpeechServers";
import { VoiceSettings } from "../../../src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/VoiceSettings";
import { RealtimeASRSettings } from "../../../src-ui/views/app/config_page/setting_section/setting_box/transcription/RealtimeASRSettings";
import "../../../locales/config";

store.backend_subprocess = { write: line => window.sidecarWrite(line) };
window.received = [];
function App() {
    const receiver = useRef();
    receiver.current = useReceiveRoutes().receiveRoutes;
    useEffect(() => {
        let active = true;
        const poll = async () => {
            for (const line of await window.sidecarRead()) {
                const response = JSON.parse(line);
                receiver.current(response);
                window.received.push(response._test_reply_id);
            }
            if (active) setTimeout(poll, 20);
        };
        poll();
        return () => { active = false; };
    }, []);
    return <main style={{ maxWidth: 900, margin: "24px auto", color: "#222", background: "#fff" }}>
        <VoiceSettings /><SpeechServers /><RealtimeASRSettings />
    </main>;
}
createRoot(document.getElementById("root")).render(<App />);
