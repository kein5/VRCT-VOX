import { useMemo, useRef } from "react";
import { getDefaultStore } from "jotai";
import { invoke } from "@tauri-apps/api/core";
import { Atom_OcrSharedWindow, dynamicStoreRegistry, useStore_OcrSharedWindow } from "@store";
import { useStdoutToPython } from "@useStdoutToPython";
import { createSharedWindowActions, startErrorKey } from "./ocrSharedWindow.js";

const atoms = getDefaultStore();

// The notice for a chat-reading start error, given what is known about this desktop when it arrives.
export const ocrStartErrorKey = error_code => startErrorKey(error_code, atoms.get(Atom_OcrSharedWindow).data);

// Sharing a window with Chat Transcribe (Linux, Wayland). `share` is for the user's button
// only: it makes the desktop show its window dialog.
export const useOcrSharedWindow = () => {
    const { currentOcrSharedWindow } = useStore_OcrSharedWindow();
    const { asyncStdoutToPython } = useStdoutToPython();
    const send = useRef(asyncStdoutToPython);
    send.current = asyncStdoutToPython;
    const actions = useMemo(() => createSharedWindowActions({
        invoke,
        read: () => atoms.get(Atom_OcrSharedWindow).data,
        write: data => atoms.set(Atom_OcrSharedWindow, { state: "ok", data }),
        token: () => atoms.get(dynamicStoreRegistry.Atom_OcrPortalRestoreToken)?.data ?? "",
        saveToken: value => send.current("/set/data/ocr_portal_restore_token", value),
    }), []);
    return { currentOcrSharedWindow, ...actions };
};
