import React, { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { store } from "@store";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { SpeechServers } from "../../../src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/SpeechServers";
import { ModelDownloads } from "../../../src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/ModelDownloads";
import "../../../locales/config";
store.backend_subprocess = { write: line => window.sidecarWrite(line) };
function App() {
    const receiver = useRef(); receiver.current = useReceiveRoutes().receiveRoutes;
    useEffect(() => {
        let active = true;
        const poll = async () => { for (const response of await window.sidecarRead()) receiver.current(response); if (active) setTimeout(poll, 20); };
        poll(); return () => { active = false; };
    }, []);
    return <main style={{ maxWidth: 900, margin: 24, color: "#222", background: "#fff" }}>
        <SpeechServers profiles={["japanese"]} /><ModelDownloads targets={["rvc"]} expected={{ rvc: { model: "", index: "" } }} />
    </main>;
}
createRoot(document.getElementById("root")).render(<App />);
