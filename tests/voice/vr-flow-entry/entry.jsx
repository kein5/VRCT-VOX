// The VR panel's "Inputs and outputs" window at its real size (the popup region of
// src-ui/views/vr/vr_layout.json), with the sample of tests/voice/fixtures/io_flow_sample.json
// in the atoms the main window mirrors to VR. For the documentation's picture and a look.
import React from "react";
import { createRoot } from "react-dom/client";
import { getDefaultStore } from "jotai";
import { dynamicStoreRegistry, Atom_IoFlow, Atom_IoTraces } from "@store";
import { VrIoFlowWindow } from "../../../src-ui/views/vr/VrIoFlowWindow";
import "../../../src-ui/views/app/_index_css/root.css";
import i18n from "../../../locales/config";
import sample from "../fixtures/io_flow_sample.json";
import layout from "../../../src-ui/views/vr/vr_layout.json";

i18n.changeLanguage(new URLSearchParams(location.search).get("lang") || "ja");
const atoms = getDefaultStore();
for (const [name, atom] of Object.entries(dynamicStoreRegistry)) {
    if (name.startsWith("Atom_")) atoms.set(atom, { ...atoms.get(atom), state: "ok" });
}
atoms.set(Atom_IoFlow, { state: "ok", data: sample.flow });
atoms.set(Atom_IoTraces, { state: "ok", data: sample.traces });
const [, , width, height] = layout.regions.popup;

createRoot(document.getElementById("root")).render(
    <div style={{ width, height, background: "var(--dark_1000_color)" }}>
        <VrIoFlowWindow onClose={() => {}} />
    </div>,
);