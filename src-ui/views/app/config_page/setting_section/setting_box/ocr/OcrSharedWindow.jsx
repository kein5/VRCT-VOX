import { useEffect, useRef } from "react";
import { useI18n } from "@useI18n";
import { useOcrSharedWindow } from "@logics_configs";
import { sharedWindowView } from "../../../../../../logics/configs/ocrSharedWindow";
import { EnvReadout } from "../_components/env_readout/EnvReadout";
import styles from "./Ocr.module.scss";

// Linux on Wayland: share one window with Chat Transcribe through the desktop's own dialog.
// For a VRChat window that cannot be found by its name (native Wayland). Shown nowhere else.
export const OcrSharedWindow = () => {
    const { t } = useI18n();
    const { currentOcrSharedWindow, refresh, share, stop } = useOcrSharedWindow();
    const shareButton = useRef(null);
    useEffect(() => { refresh(); }, []);
    const view = sharedWindowView(currentOcrSharedWindow.data);
    if (!view.visible) return null;
    const label = t("config_page.ocr.shared_window.label");
    const active = currentOcrSharedWindow.data.active === true;
    return (
        <section className={styles.region} aria-label={label}>
            <p className={styles.regionLabel}>{label}</p>
            <p className={styles.regionDesc}>{t("config_page.ocr.shared_window.desc")}</p>
            <EnvReadout className={styles.sharedStatus} tone={view.tone}>
                <p>{t(view.statusKey)}</p>
                {view.errorKey && <p>{t(view.errorKey, { code: view.errorCode })}</p>}
            </EnvReadout>
            <div className={styles.sharedActions}>
                {/* aria-disabled keeps the keyboard focus here while the desktop's dialog is open. */}
                <button type="button" ref={shareButton} className={styles.resetButton} aria-disabled={!view.canShare}
                    onClick={() => { if (view.canShare) share({ choose: active }); }}>
                    {t(view.shareKey)}
                </button>
                {view.canStop &&
                    <button type="button" className={styles.resetButton}
                        onClick={async () => { await stop(); shareButton.current?.focus(); }}>
                        {t("config_page.ocr.shared_window.stop")}
                    </button>}
            </div>
        </section>
    );
};
