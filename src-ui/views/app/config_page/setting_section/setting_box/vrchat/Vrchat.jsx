import { useI18n } from "@useI18n";
import styles from "./Vrchat.module.scss";

import { SectionLabelComponent } from "../_components";
import {
    SendMessageToVrcContainer,
    SendOnlyTranslatedMessagesContainer,
    EnableNotificationVrcSfxContainer,
    SendReceivedMessageToVrcContainer,
    VrcMicMuteSyncContainer,
    SendMessageFormatPartsContainer,
    ReceivedMessageFormatPartsContainer,
} from "../shared_items/SharedItems";
import { OscIpAddressContainer, OscPortContainer } from "../advanced_settings/AdvancedSettings";
import { VoiceRouteSettings } from "../device/VoiceRouteSettings";
import { TtsOutputDeviceSettings } from "../advanced_settings/VoiceSettings";
import { useStore_SelectedConfigTabId } from "@store";
import { Description } from "../_components/description/Description";
import { VrchatPresence } from "../../../../others/vrchat_presence/VrchatPresence";

// What goes to VRChat: the chatbox, OSC and the voice that reaches VRChat's
// microphone. The voice route, the TTS output device and mic mute sync also
// stay on their own pages. Reading VRChat's chatbox has a page of its own,
// named like its switch on the main page; this page ends with the way there.
export const Vrchat = () => {
    const { t } = useI18n();
    return (
        <div className={styles.container}>
            <div>
                <SectionLabelComponent label={t("config_page.vrchat.section_label_chatbox")} />
                {/* Whether a message sent now can arrive: the first thing to check on this page. */}
                <VrchatPresence />
                <SendMessageToVrcContainer />
                <SendOnlyTranslatedMessagesContainer />
                <EnableNotificationVrcSfxContainer />
                <SendReceivedMessageToVrcContainer />
                <VrcMicMuteSyncContainer />
            </div>
            <div>
                <SectionLabelComponent label={t("config_page.others.section_label_message_formats")} />
                <SendMessageFormatPartsContainer />
                <ReceivedMessageFormatPartsContainer />
            </div>
            <div>
                <SectionLabelComponent label={t("config_page.advanced_settings.section_label_osc")} />
                <OscIpAddressContainer />
                <OscPortContainer />
            </div>
            <VoiceRouteSettings />
            <TtsOutputDeviceSettings title={t("config_page.vrchat.section_label_tts_output")} />
            <ChatReadingPointer />
        </div>
    );
};

const ChatReadingPointer = () => {
    const { t } = useI18n();
    const { updateSelectedConfigTabId } = useStore_SelectedConfigTabId();
    return (
        <div>
            <SectionLabelComponent label={t("config_page.side_menu_labels.ocr")} />
            <Description text={t("config_page.vrchat.chat_reading_moved")} />
            <button type="button" className={styles.open_page} onClick={() => updateSelectedConfigTabId("ocr")}>
                {t("config_page.vrchat.open_chat_reading")}
            </button>
        </div>
    );
};
