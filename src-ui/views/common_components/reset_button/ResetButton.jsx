import styles from "./ResetButton.module.scss";
import RedoSvg from "@images/redo.svg?react";

export const ResetButton = ({ onClickFunction, label }) => {
    return (
        <button type="button" className={styles.reset_button} onClick={onClickFunction} aria-label={label}>
            <RedoSvg className={styles.reset_svg} aria-hidden="true"/>
        </button>
    );
};