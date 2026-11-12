import { atom, useAtom } from "jotai";

// Main-window only. The request to review and fetch the built-in translation
// model: raised when the user turns Translation on without it, or asks from the
// empty conversation. `resume` is true when the switch should be tried again
// once the model is there.
const requestAtom = atom(null);
export const useTranslationSetup = () => {
    const [request, setRequest] = useAtom(requestAtom);
    const open = (resume = false) => setRequest(previous => previous ?? { resume });
    return { request, open, setRequest };
};
