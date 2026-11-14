import { VrLanguageWindow } from "./VrLanguageWindow";
import { VrSettingsWindow } from "./VrSettingsWindow";
import { VrIoFlowWindow } from "./VrIoFlowWindow";

// 一時ウィンドウ (言語 / VR設定 / 入力と出力)。同時に1つだけ開く
export const VrPopupWindow = ({ popup, onClose }) => {
    if (popup === "language") {
        return <VrLanguageWindow onClose={onClose} />;
    }
    if (popup === "settings") {
        return <VrSettingsWindow onClose={onClose} />;
    }
    if (popup === "io_flow") {
        return <VrIoFlowWindow onClose={onClose} />;
    }
    return null;
};
