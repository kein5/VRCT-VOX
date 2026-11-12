import { useStore_SelectedConfigTabId } from "@store";

import {
    Device, Tts, Rvc,
    Appearance,
    Translation,
    Transcription,
    Vrchat,
    Ocr,
    AdvancedSettings,
    Vr,
    Hotkeys,
    AboutVrct,
    Updater,
} from "@setting_box";

export const SettingBox = () => {
    const { currentSelectedConfigTabId } = useStore_SelectedConfigTabId();
    switch (currentSelectedConfigTabId.data) {
        case "tts": return <Tts />;
        case "rvc": return <Rvc />;
        case "device":
            return <Device />;
        case "appearance":
            return <Appearance />;
        case "translation":
            return <Translation />;
        case "transcription":
            return <Transcription />;
        case "vr":
            return <Vr />;
        case "hotkeys":
            return <Hotkeys />;
        case "advanced_settings":
            return <AdvancedSettings />;
        case "updater":
            return <Updater />;
        // The main page has a chat reading switch, so settings have a page of that
        // name. The VRChat page shows the same settings, and holds the old "others" page.
        case "ocr":
            return <Ocr />;
        case "vrchat":
        case "others":
            return <Vrchat />;
        case "about_vrct":
            return <AboutVrct />;

        default:
            return null;
    }
};