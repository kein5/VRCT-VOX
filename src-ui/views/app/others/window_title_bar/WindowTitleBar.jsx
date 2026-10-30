import { useI18n } from "@useI18n";
import { useWindow } from "@logics_common";
// import clsx from "clsx";
import styles from "./WindowTitleBar.module.scss";
import XMarkSvg from "@images/cancel.svg?react";
import SquareSvg from "@images/square.svg?react";
import LineSvg from "@images/line.svg?react";

export const WindowTitleBar = () => {
    const { t } = useI18n();
    const { asyncCloseApp, asyncToggleMaximizeApp, asyncMinimizeApp} = useWindow();

    return (
        <div className={styles.container}>
            <div className={styles.wrapper} data-tauri-drag-region>
                <div className={styles.title_wrapper}>
                    <span>VRCT-VOX</span>
                </div>

                <div className={styles.window_control_wrapper}>
                    <button type="button" aria-label={t("studio.minimize")} className={styles.minimize_button} onClick={asyncMinimizeApp}>
                        <LineSvg aria-hidden="true" className={styles.line_svg}/>
                    </button>
                    <button type="button" aria-label={t("studio.maximize")} className={styles.maximize_button} onClick={asyncToggleMaximizeApp}>
                        <SquareSvg aria-hidden="true" className={styles.square_svg}/>
                    </button>
                    <button type="button" aria-label={t("studio.close")} className={styles.close_button} onClick={asyncCloseApp}>
                        <XMarkSvg aria-hidden="true" className={styles.x_mark_svg}/>
                    </button>
                </div>
            </div>
        </div>
    );
};
