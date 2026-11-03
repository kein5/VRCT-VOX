import { useRef } from "react";
import { useI18n } from "@useI18n";
import { useVr } from "@logics_configs";

import CopyThinSvg from "@images/copy_thin.svg?react";
import { LogBox } from "../app/main_page/main_section/message_container/log_box/LogBox";

import { VrWindow } from "./VrWindow";
import styles from "./VrWindow.module.scss";

// ログウィンドウ。固定先・ロックなどは下の操作バー (VrToolbar) で変える
export const VrLogWindow = ({ open, onClose }) => {
    // Keep only the view snapshot while closed; no log body or atom subscriber.
    const savedView = useRef(null);
    return open ? <VrLogBody onClose={onClose} savedView={savedView} /> : null;
};

const VrLogBody = ({ onClose, savedView }) => {
    const { t } = useI18n();
    const { currentOverlayVrPanelLocked, currentOverlayVrPanelFontSize } = useVr();
    return (
        <VrWindow Icon={CopyThinSvg} title={t("vr_panel.window_log")} onClose={onClose}
            is_grab_locked={currentOverlayVrPanelLocked.data === true} is_resizable={true}>
            <div className={styles.log_box_wrapper} style={{ "--vr_log_font_size": `${currentOverlayVrPanelFontSize.data}px` }}>
                <LogBox savedView={savedView} />
            </div>
        </VrWindow>
    );
};
