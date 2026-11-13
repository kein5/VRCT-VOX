import { useEffect, useState } from "react";
import { useI18n } from "@useI18n";
import { useOthers } from "@logics_configs";
import { useConsentDialog } from "../../../logics/common/useConsentDialog";
import { TelemetryContents } from "../config_page/setting_section/setting_box/_components/telemetry/TelemetryContents";
import styles from "../config_page/setting_section/setting_box/advanced_settings/VoiceSettings.module.scss";
import dialogStyles from "../config_page/setting_section/setting_box/_components/download_models/LegacyModelDownloadDialog.module.scss";

// Usage events are sent unless the user turns them off, but never before the user has
// been told. This asks once: what is sent, what is not, the event itself as this PC would
// send it (TelemetryContents), and the two answers. The backend
// sends nothing while the notice is pending, so closing the app here leaves it unanswered
// and unsent. Escape does not answer for the user.
export const TelemetryNoticeController = () => {
    const { t } = useI18n();
    const { currentTelemetryNotice, setTelemetryNotice, getTelemetry } = useOthers();
    const pending = currentTelemetryNotice.state === "ok" && currentTelemetryNotice.data?.pending === true;
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
    return <div className={`${styles.container} ${dialogStyles.host}`}>
        <dialog ref={dialog} className={dialogStyles.dialog} aria-label={t("telemetry_notice.title")}
            onCancel={event => event.preventDefault()}>
            <h3>{t("telemetry_notice.title")}</h3>
            <p>{t("telemetry_notice.what")}</p>
            <p>{t("telemetry_notice.not_sent")}</p>
            <p>{t("telemetry_notice.change")}</p>
            <TelemetryContents />
            <div className={styles.actions}>
                {/* Neither answer takes the first focus: the dialog opens with it on "See what is sent" above. */}
                <button type="button" disabled={answered} onClick={() => answer(true)}>{t("telemetry_notice.send")}</button>
                <button type="button" disabled={answered} onClick={() => answer(false)}>{t("telemetry_notice.dont_send")}</button>
            </div>
        </dialog>
    </div>;
};
