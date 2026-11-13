import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useOthers } from "@logics_configs";
import { useConsentDialog } from "../../../logics/common/useConsentDialog";
import { TelemetryContents } from "../config_page/setting_section/setting_box/_components/telemetry/TelemetryContents";
import styles from "../config_page/setting_section/setting_box/advanced_settings/VoiceSettings.module.scss";
import dialogStyles from "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog.module.scss";
import noticeStyles from "./TelemetryNoticeController.module.scss";

// Usage events are sent unless the user turns them off, but never before the user has
// been told. This asks: why, what is sent, what is not, the event itself as this PC would
// send it (TelemetryContents), and the two answers. The backend sends nothing while the
// notice is pending.
//
// The user is not held here. "Decide later" (and Escape) puts the notice away for this
// run without an answer: nothing is sent, and the next start asks again. While a modal
// dialog is open the window's own buttons, drawn in this page, cannot be pressed, so
// without it the app could not even be closed from its title bar.
export const TelemetryNoticeController = () => {
    const { t } = useI18n();
    const { currentTelemetryNotice, setTelemetryNotice, getTelemetry } = useOthers();
    const [later, setLater] = useState(false);
    const pending = !later && currentTelemetryNotice.state === "ok" && currentTelemetryNotice.data?.pending === true;
    const { dialog } = useConsentDialog(pending);
    const [answered, setAnswered] = useState(false);
    // A refused or lost answer leaves the notice pending: let the user answer again.
    useEffect(() => { if (currentTelemetryNotice.state !== "pending") setAnswered(false); },
        [currentTelemetryNotice.state, currentTelemetryNotice.data]);

    if (!pending) return null;
    const answer = async send => {
        if (answered) return;
        setAnswered(true);
        await setTelemetryNotice({ send });
        // The switch in the settings shows the same choice.
        getTelemetry();
    };
    // Not once an answer is on its way: that answer stands.
    const putAway = () => { if (!answered) setLater(true); };
    return <div className={`${styles.container} ${dialogStyles.host}`}>
        <dialog ref={dialog} className={dialogStyles.dialog} aria-label={t("telemetry_notice.title")}
            onCancel={event => { event.preventDefault(); putAway(); }}>
            {/* Why it is asked comes first; then what is sent, what is not, and how to change it. */}
            <div className={noticeStyles.notice}>
                <h3>{t("telemetry_notice.title")}</h3>
                <p className={noticeStyles.purpose}>{t("telemetry_notice.purpose")}</p>
                <p>{t("telemetry_notice.what")}</p>
                <p>{t("telemetry_notice.not_sent")}</p>
                <p>{t("telemetry_notice.change")}</p>
            </div>
            <TelemetryContents />
            <div className={styles.actions}>
                {/* Neither answer takes the first focus: the dialog opens with it on "See what is sent" above. */}
                <button type="button" disabled={answered} onClick={() => answer(true)}>{t("telemetry_notice.send")}</button>
                <button type="button" disabled={answered} onClick={() => answer(false)}>{t("telemetry_notice.dont_send")}</button>
            </div>
            <div className={dialogStyles.alternative}>
                <button type="button" disabled={answered} onClick={putAway}>{t("telemetry_notice.later")}</button>
            </div>
        </dialog>
    </div>;
};
