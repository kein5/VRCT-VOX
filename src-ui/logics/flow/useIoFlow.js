import { useCallback } from "react";
import { getDefaultStore } from "jotai";
import { Atom_IoFlow, Atom_IoTraces, useStore_IoFlow, useStore_IoTraces, useStore_IsOpenedIoFlowPanel } from "@store";
import { mergeTrace } from "./ioFlow.js";

// The flow panel's state lives in registered atoms, so the VR window mirrors it as it is.
export const useIoFlow = () => {
    const { currentIoFlow } = useStore_IoFlow();
    const { currentIoTraces } = useStore_IoTraces();
    const { currentIsOpenedIoFlowPanel, updateIsOpenedIoFlowPanel } = useStore_IsOpenedIoFlowPanel();

    // Polled every second; an unchanged map is not set again (the VR mirror sends every change).
    const updateIoFlow = useCallback(result => {
        if (!result || typeof result !== "object" || !result.voice || !result.chat) return;
        const atoms = getDefaultStore();
        const previous = atoms.get(Atom_IoFlow);
        if (previous.state === "ok" && JSON.stringify(previous.data) === JSON.stringify(result)) return;
        atoms.set(Atom_IoFlow, { state: "ok", data: result });
    }, []);

    const addIoTrace = useCallback(trace => {
        const atoms = getDefaultStore();
        const previous = atoms.get(Atom_IoTraces);
        const next = mergeTrace(previous.data, trace);
        if (next !== previous.data) atoms.set(Atom_IoTraces, { state: "ok", data: next });
    }, []);

    return {
        currentIoFlow, currentIoTraces, updateIoFlow, addIoTrace,
        isPanelOpen: currentIsOpenedIoFlowPanel.data === true,
        togglePanel: () => updateIsOpenedIoFlowPanel(open => !(open.data === true)),
    };
};
