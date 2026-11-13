import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { HexColorPicker } from "react-colorful";

import styles from "./ColorEntryWithSaveButton.module.scss";
import { _Entry } from "../_atoms/_entry/_Entry";
import { clsx } from "clsx";
import { useI18n } from "@useI18n";

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const PICKER_GAP_REM = 0.4;
const VIEWPORT_PADDING_REM = 0.8;

const remToPx = (rem) => {
    const root_font_size = parseFloat(getComputedStyle(document.documentElement).fontSize);
    return rem * root_font_size;
};

export const ColorEntryWithSaveButton = (props) => {
    const { t } = useI18n();
    const is_disabled = props.state === "pending";
    const [is_open, setIsOpen] = useState(false);
    const [placement, setPlacement] = useState({ open_above: true, align_end: true });
    const popover_ref = useRef(null);
    const swatch_ref = useRef(null);

    const current_color = typeof props.variable === "string" ? props.variable.trim() : "";
    const is_valid_color = HEX_COLOR_RE.test(current_color);
    const swatch_color = is_valid_color ? current_color : "transparent";
    const picker_color = is_valid_color ? current_color : "#FFFFFF";

    const onChangeFunction = (e) => {
        if (props.state === "pending") return;
        props.onChangeFunction?.(e.target.value);
    };

    const onPickerChange = (color) => {
        if (props.state === "pending") return;
        props.onChangeFunction?.(color);
    };

    const openPicker = () => {
        if (is_disabled) return;
        setIsOpen(true);
    };

    const closePicker = () => {
        setIsOpen(false);
    };

    const saveFunction = () => {
        closePicker();
        props.saveFunction();
    };

    useLayoutEffect(() => {
        if (!is_open) return;

        const updatePlacement = () => {
            const swatch = swatch_ref.current;
            const popover = popover_ref.current;
            if (!swatch || !popover) return;

            const swatch_rect = swatch.getBoundingClientRect();
            const popover_height = popover.offsetHeight;
            const popover_width = popover.offsetWidth;
            const gap = remToPx(PICKER_GAP_REM);
            const viewport_padding = remToPx(VIEWPORT_PADDING_REM);

            const space_below = window.innerHeight - swatch_rect.bottom - gap - viewport_padding;
            const space_above = swatch_rect.top - gap - viewport_padding;
            const space_right = window.innerWidth - swatch_rect.left - viewport_padding;

            setPlacement({
                open_above: space_below < popover_height && space_above > space_below,
                align_end: space_right < popover_width,
            });
        };

        updatePlacement();
        window.addEventListener("resize", updatePlacement);
        return () => {
            window.removeEventListener("resize", updatePlacement);
        };
    }, [is_open]);

    useEffect(() => {
        if (!is_open) return;
        const onDocumentMouseDown = (event) => {
            if (popover_ref.current?.contains(event.target)) return;
            if (swatch_ref.current?.contains(event.target)) return;
            closePicker();
        };
        const onKeyDown = (event) => {
            if (event.key === "Escape") closePicker();
        };
        document.addEventListener("mousedown", onDocumentMouseDown);
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("mousedown", onDocumentMouseDown);
            document.removeEventListener("keydown", onKeyDown);
        };
    }, [is_open]);

    const swatch_button_class_names = clsx(styles.swatch_button, {
        [styles.is_disabled]: is_disabled,
    });

    const popover_paper_class_names = clsx(
        styles.popover_paper,
        placement.open_above ? styles.open_above : styles.open_below,
        placement.align_end ? styles.align_end : styles.align_start,
    );

    const handleEnterPressed = () => {
        if (is_disabled) return;
        saveFunction();
    };

    return (
        <div className={styles.container}>
            <_Entry
                label={props.label}
                width={props.width}
                onChange={onChangeFunction}
                onEnterPressed={handleEnterPressed}
                ui_variable={props.variable}
                readOnly={is_disabled} aria-busy={is_disabled} aria-disabled={is_disabled} aria-describedby={props["aria-describedby"]}
            />
            <div className={styles.swatch_wrapper}>
                <button
                    ref={swatch_ref}
                    className={swatch_button_class_names}
                    type="button"
                    aria-label={t("config_page.common.open_color_picker", { label: props.label })}
                    aria-expanded={is_open}
                    aria-disabled={is_disabled}
                    onClick={openPicker}
                >
                    <span className={styles.swatch} style={{ backgroundColor: swatch_color }} />
                </button>
                {is_open && (
                    <div ref={popover_ref} className={popover_paper_class_names}>
                        <div className={styles.popover_content}>
                            <HexColorPicker color={picker_color} onChange={onPickerChange} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
