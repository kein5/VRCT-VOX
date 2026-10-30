// Production screen composition with a model-free transport supplied by Playwright.
import React, { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { getDefaultStore } from "jotai";
import { store, dynamicStoreRegistry, Atom_IsBreakPoint, Atom_SoftwareVersion } from "@store";
import { useReceiveRoutes } from "@useReceiveRoutes";
import { MainPage } from "../../../src-ui/views/app/main_page/MainPage";
import { ConfigPage } from "../../../src-ui/views/app/config_page/ConfigPage";
import { WindowTitleBar } from "../../../src-ui/views/app/others/window_title_bar/WindowTitleBar";
import { SnackbarController } from "../../../src-ui/views/app/others/snackbar_controller/SnackbarController";
import styles from "../../../src-ui/views/app/App.module.scss";
import "../../../src-ui/views/app/_index_css/root.css";
import i18n from "../../../locales/config";

i18n.changeLanguage(new URLSearchParams(location.search).get("lang") || "ja");
const atoms = getDefaultStore();
for (const [name, atom] of Object.entries(dynamicStoreRegistry)) {
    if (name.startsWith("Atom_")) atoms.set(atom, { ...atoms.get(atom), state: "ok" });
}
for (const [key, language, country] of [["SelectedYourLanguages", "Japanese", "Japan"], ["SelectedTargetLanguages", "English", "United States"]]) {
    const presets = Object.fromEntries(["1", "2", "3"].map(preset => [preset, Object.fromEntries(["1", "2", "3"].map(slot => [slot, { language, country, enable: slot === "1" }]))]));
    atoms.set(dynamicStoreRegistry[`Atom_${key}`], { state: "ok", data: presets });
}
for (const key of ["SendMessageFormatParts", "ReceivedMessageFormatParts"]) {
    atoms.set(dynamicStoreRegistry[`Atom_${key}`], { state: "ok", data: { message: { prefix: "", suffix: "" }, separator: "\n", translation: { prefix: "", suffix: "", separator: "\n" }, translation_first: false } });
}
atoms.set(Atom_SoftwareVersion, { state: "ok", data: "3.6.0-beta.1" });
store.backend_subprocess = { write: line => window.sidecarWrite(line) };
store.appWindow = { innerSize: async () => ({ width: innerWidth, height: innerHeight }), isMaximized: async () => false, maximize: async () => {}, minimize: async () => {}, close: async () => {} };
function Studio() {
    const receiver = useRef();
    receiver.current = useReceiveRoutes().receiveRoutes;
    useEffect(() => {
        let active = true;
        const resize = () => atoms.set(Atom_IsBreakPoint, { state: "ok", data: innerWidth <= 800 });
        resize();
        window.addEventListener("resize", resize);
        const poll = async () => {
            for (const response of await window.sidecarRead()) receiver.current(response);
            if (active) setTimeout(poll, 20);
        };
        poll();
        return () => { active = false; window.removeEventListener("resize", resize); };
    }, []);
    return <div className={styles.container}><WindowTitleBar /><div className={styles.pages_wrapper}><ConfigPage /><MainPage /></div><SnackbarController /></div>;
}
createRoot(document.getElementById("root")).render(<Studio />);
