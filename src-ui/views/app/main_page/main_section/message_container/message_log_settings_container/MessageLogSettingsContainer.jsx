import { useState } from "react";
import styles from "./MessageLogSettingsContainer.module.scss";
import clsx from "clsx";
import { useI18n } from "@useI18n";

import { MessageLogUiScalingContainer } from "@setting_box";
import ConfigSvg from "@images/configuration.svg?react";

export const MessageLogSettingsContainer = (props) => {
    const { t } = useI18n();
    const [is_opened, setIsOpened] = useState(false);
    const [is_hovered, setIsHovered] = useState(false);

    const container_class_name = clsx(styles.container, {
        [styles.to_visible_toggle_bar]: props.to_visible_toggle_bar,
        [styles.is_hovered]: is_hovered,
        [styles.is_opened]: is_opened
    });

    return (
        <div className={container_class_name}
            onMouseOver={() => setIsHovered(true)}
            onMouseLeave={() => {setIsHovered(false); setIsOpened(false);}}
            onClick={() => setIsOpened(true)}
            /* Keyboard: focus shows the tab, the gear opens it, Escape or
               leaving with focus closes it. */
            onFocus={() => setIsHovered(true)}
            onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) { setIsHovered(false); setIsOpened(false); } }}
            onKeyDown={event => { if (event.key === "Escape") setIsOpened(false); }}
        >
            <div className={styles.container_relative_wrapper}>
                <div className={styles.config_svg_wrapper} role="button" tabIndex={0} aria-expanded={is_opened}
                    aria-label={t("config_page.appearance.textbox_ui_size.label")}
                    onClick={event => { event.stopPropagation(); setIsOpened(!is_opened); }}
                    onKeyDown={event => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); setIsOpened(!is_opened); } }}>
                    <ConfigSvg className={styles.config_svg} aria-hidden="true"/>
                </div>
            </div>
            <MessageLogUiScalingContainer />
            <div className={styles.others_wrapper}>
            </div>
        </div>
    );
};