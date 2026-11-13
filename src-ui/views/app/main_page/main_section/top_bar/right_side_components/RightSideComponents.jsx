import { useEffect, useId, useRef, useState } from "react";
import clsx from "clsx";
import { useI18n } from "@useI18n";
import styles from "./RightSideComponents.module.scss";
import RefreshSvg from "@images/refresh.svg?react";
import HelpSvg from "@images/help.svg?react";
import TuneSvg from "@images/mui_discover_tune.svg?react";

import { useStore_OpenedQuickSetting } from "@store";
import {
    useSoftwareVersion,
    useIsOscAvailable,
} from "@logics_common";

import {
    useAppearance,
    useVr,
    useOthers,
} from "@logics_configs";
import { useMainFunction } from "@logics_main";
import { OpenQuickSettingButton } from "./_buttons/OpenQuickSettingButton";
import { VrchatPresence } from "../../../../others/vrchat_presence/VrchatPresence";

import { generateLocalizedDocumentUrl } from "@ui_configs";

export const RightSideComponents = () => {
    const { t } = useI18n();
    const { currentUiLanguage } = useAppearance();

    return (
        <div className={styles.container}>
            <SoftwareUpdateAvailableButton />
            <QuickSettingsMenu />
            <a
                className={styles.help_and_info_button}
                aria-label={t("main_page.help_link")}
                title={t("main_page.help_link")}
                href={generateLocalizedDocumentUrl(currentUiLanguage.data).vrct_document_ui_guide_url}
                target="_blank"
                rel="noreferrer"
            >
                <HelpSvg className={styles.help_svg} aria-hidden="true" />
            </a>
        </div>
    );
};

// The window and VRChat toggles a conversation rarely needs: always on top,
// VRChat microphone mute sync and the subtitle overlay. One button opens them
// and says how many are on, so the bar keeps its room for stop and mute.
// It closes with Escape (focus returns to the button), a press outside, or
// when focus moves elsewhere.
const QuickSettingsMenu = () => {
    const { t } = useI18n();
    const { currentForegroundStatus, toggleForeground } = useMainFunction();
    const { currentIsOscAvailable, oscUnavailableLabelKey } = useIsOscAvailable();
    const { currentEnableVrcMicMuteSync, toggleEnableVrcMicMuteSync } = useOthers();
    const { currentIsEnabledOverlaySmallLog, currentIsEnabledOverlayLargeLog } = useVr();
    const { updateOpenedQuickSetting } = useStore_OpenedQuickSetting();
    const [open, setOpen] = useState(false);
    const root = useRef(null), opener = useRef(null);
    const panel = useId();

    useEffect(() => {
        if (!open) return;
        const leave = event => { if (!root.current?.contains(event.target)) setOpen(false); };
        const escape = event => {
            if (event.key !== "Escape") return;
            setOpen(false);
            opener.current?.focus();
        };
        document.addEventListener("pointerdown", leave);
        document.addEventListener("focusin", leave);
        document.addEventListener("keydown", escape);
        return () => {
            document.removeEventListener("pointerdown", leave);
            document.removeEventListener("focusin", leave);
            document.removeEventListener("keydown", escape);
        };
    }, [open]);

    const overlay = currentIsEnabledOverlaySmallLog.data === true || currentIsEnabledOverlayLargeLog.data === true;
    const on = [currentForegroundStatus.data, currentEnableVrcMicMuteSync.data, overlay].filter(value => value === true).length;
    const sync_available = currentIsOscAvailable.data !== false;

    return (
        <div ref={root} className={styles.menu}>
            <button ref={opener} type="button" className={clsx(styles.menu_button, { [styles.has_on]: on > 0 })}
                aria-expanded={open} aria-controls={panel} title={t("main_page.quick_settings")}
                onClick={() => setOpen(value => !value)}>
                <TuneSvg className={styles.menu_svg} aria-hidden="true" />
                <span className={styles.menu_text}>
                    <span className={styles.menu_label}>{t("main_page.quick_settings")}</span>
                    <span className={styles.menu_state}>
                        {on > 0 ? t("main_page.quick_settings_on", { count: on }) : t("main_page.quick_settings_all_off")}
                    </span>
                </span>
            </button>
            {open && <div id={panel} className={styles.menu_panel} role="group" aria-label={t("main_page.quick_settings")}>
                <OpenQuickSettingButton
                    row
                    label={t("main_page.foreground")}
                    variable={currentForegroundStatus.data}
                    state={currentForegroundStatus.state}
                    onClickFunction={toggleForeground}
                />
                <OpenQuickSettingButton
                    row
                    label={t("config_page.others.vrc_mic_mute_sync.label")}
                    variable={currentEnableVrcMicMuteSync.data}
                    state={currentEnableVrcMicMuteSync.state}
                    is_available={currentIsOscAvailable.data}
                    note={sync_available ? null : t(oscUnavailableLabelKey)}
                    onClickFunction={() => { if (sync_available) toggleEnableVrcMicMuteSync(); }}
                />
                <OpenQuickSettingButton
                    row
                    label={t("config_page.vr.section_label_overlay")}
                    opens_dialog
                    variable={overlay}
                    onClickFunction={() => { setOpen(false); updateOpenedQuickSetting("overlay"); }}
                />
                {/* Within reach of the conversation: can a message sent now arrive in VRChat? */}
                <VrchatPresence className={styles.menu_readout} />
            </div>}
        </div>
    );
};

const SoftwareUpdateAvailableButton = () => {
    const { t } = useI18n();
    const { currentLatestSoftwareVersionInfo } = useSoftwareVersion();
    const { updateOpenedQuickSetting } = useStore_OpenedQuickSetting();

    if (currentLatestSoftwareVersionInfo.data.is_update_available === false) return null;

    return (
        <button className={styles.software_update_button} onClick={()=>updateOpenedQuickSetting("update_software")}>
            <RefreshSvg className={styles.refresh_svg}/>
            <p className={styles.software_update_label}>{t("main_page.update_available")}</p>
        </button>
    );
};
