import { useI18n } from "@useI18n";
import FlowSvg from "@images/io_flow.svg?react";
import { useIoFlow } from "../../logics/flow/useIoFlow";
import { IoFlowView } from "../app/io_flow/IoFlowView";
import { VrWindow } from "./VrWindow";
import styles from "./VrIoFlowWindow.module.scss";

// Where the user's voice and chat go, and how long the latest of each took, in VR. The same
// view as the main window's panel, mirrored from it (VrPanelSyncController). It only reads,
// so the settings page being open does not lock it.
export const VrIoFlowWindow = ({ onClose }) => {
    const { t } = useI18n();
    const { currentIoFlow, currentIoTraces } = useIoFlow();
    return <VrWindow Icon={FlowSvg} title={t("io_flow.vr_window")} onClose={onClose} is_lockable={false}>
        <div className={styles.body}>
            <IoFlowView flow={currentIoFlow.data} traces={currentIoTraces.data} compact />
        </div>
    </VrWindow>;
};
