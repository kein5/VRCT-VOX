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
import { Ocr } from "../ocr/Ocr";

// Everything that talks to VRChat: the chatbox, OSC, the voice that reaches
// VRChat's microphone, and reading VRChat's chatbox. The voice route, the TTS
// output device and mic mute sync also stay on their own pages.
export const Vrchat = () => {
    const { t } = useI18n();
    return (
        <div className={styles.container}>
            <div>
                <SectionLabelComponent label={t("config_page.vrchat.section_label_chatbox")} />
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
            <Ocr />
        </div>
    );
};
