import { useMemo, useRef } from "react";
import { getDefaultStore } from "jotai";
import { invoke } from "@tauri-apps/api/core";
import { Atom_OcrSharedWindow, dynamicStoreRegistry, useStore_OcrSharedWindow } from "@store";
import { useStdoutToPython } from "@useStdoutToPython";
import { createSharedWindowActions, shouldRestoreSharing, startErrorKey } from "./ocrSharedWindow.js";

const atoms = getDefaultStore();

// The notice for a chat-reading start error, given what is known about this desktop when it arrives.
export const ocrStartErrorKey = error_code => startErrorKey(error_code, atoms.get(Atom_OcrSharedWindow).data);

// Chat reading could not start with `error_code`: is there a remembered window to share again first?
export const ocrShouldRestoreSharedWindow = error_code => shouldRestoreSharing(error_code,
    atoms.get(Atom_OcrSharedWindow).data, atoms.get(dynamicStoreRegistry.Atom_OcrPortalRestoreToken)?.data ?? "");

// Sharing a window with chat reading (Linux, Wayland). `share` is for the user's button
// only: it makes the desktop show its window dialog. `restore` is for the moment the user
// turns chat reading on and the VRChat window is not found by its name.
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
