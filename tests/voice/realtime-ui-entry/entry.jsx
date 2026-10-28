import React, { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { store, useStore_MessageLogs } from "@store";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { RealtimeASRSettings } from "../../../src-ui/views/app/config_page/setting_section/setting_box/transcription/RealtimeASRSettings";
import "../../../locales/config";

store.backend_subprocess = { write: line => window.sidecarWrite(line) };
window.entry = {};
function App() {
    const { receiveRoutes } = useReceiveRoutes();
    const { currentMessageLogs } = useStore_MessageLogs();
    const receiver = useRef(receiveRoutes);
    receiver.current = receiveRoutes;
    window.entry.logs = currentMessageLogs.data;
    useEffect(() => {
        let active = true;
        const poll = async () => {
            for (const line of await window.sidecarRead()) receiver.current(JSON.parse(line));
            if (active) setTimeout(poll, 20);
        };
        poll();
        return () => { active = false; };
    }, []);
    return <main style={{ maxWidth: 900, margin: "24px auto", color: "#222", background: "#fff" }}>
        <RealtimeASRSettings />
        <pre>{JSON.stringify(currentMessageLogs.data)}</pre>
    </main>;
}
createRoot(document.getElementById("root")).render(<App />);
