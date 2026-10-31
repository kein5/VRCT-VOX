import React, { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { getDefaultStore } from "jotai";
import { store, Atom_SelectedConfigTabId } from "@store";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { useConfigSearch } from "../../../src-ui/logics/configs/config_page_setter/_aux/useConfigSearch";
import { SidebarSection } from "../../../src-ui/views/app/config_page/sidebar_section/SidebarSection";
import { SettingBox } from "../../../src-ui/views/app/config_page/setting_section/setting_box/SettingBox";
import { MainFunctionSwitch } from "../../../src-ui/views/app/main_page/sidebar_section/main_function_switch/MainFunctionSwitch";
import { SnackbarController } from "../../../src-ui/views/app/others/snackbar_controller/SnackbarController";
import { SaveBar } from "../../../src-ui/views/app/config_page/topbar/Topbar";
import "../../../locales/config";

getDefaultStore().set(Atom_SelectedConfigTabId, { data: "tts", state: "ok" });
store.backend_subprocess = { write: line => window.voiceWrite(line) };
window.received = [];
function App() {
    const receiver = useRef();
    receiver.current = useReceiveRoutes().receiveRoutes;
    const search = useConfigSearch();
    useEffect(() => {
        let active = true;
        receiver.current({ endpoint: "/run/initialization_complete", status: 200, result: {} });
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
    if (new URLSearchParams(location.search).has("main")) return <><MainFunctionSwitch /><SnackbarController /></>;
    return <>
        <MainFunctionSwitch /><SnackbarController />
        <label>Search settings<input value={search.query} onChange={e => search.setQuery(e.target.value)} /></label>
        <div aria-label="Search results">{search.results.map(r => <button key={`${r.tab}:${r.setting_id}`}
            onClick={() => search.navigateToSetting(r)}>{r.tab_label}: {r.label}</button>)}</div>
        <div style={{ display: "flex", alignItems: "start" }}><SidebarSection /><main style={{ width: 850 }}><SaveBar /><SettingBox /></main></div>
    </>;
}
createRoot(document.getElementById("root")).render(<App />);
