import { atom, useAtom } from "jotai";

// Main-window only. A rejected enable request is the sole source of a continuation.
const requestAtom = atom(null);
export const useTranscriptionConsent = () => {
    const [request, setRequest] = useAtom(requestAtom);
    const open = (endpoint, mode = "choose") => {
        if (!["/set/enable/transcription_send", "/set/enable/transcription_receive"].includes(endpoint)) return;
        setRequest(previous => previous ?? { endpoint, mode });
    };
    return { request, open, setRequest };
};
