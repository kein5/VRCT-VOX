import React, { useRef, useState, useEffect, useCallback } from "react";
import styles from "./Slider.module.scss";
import clsx from "clsx";
import { useSliderLogic } from "@logics_configs";

export const Slider = (props) => {
    const location = props.valueLabelDisplayLocation || "top";
    const {
        ui_value,
        onChangeFunction,
        onChangeCommittedFunction,
        marks
    } = useSliderLogic({
        variable: props.variable,
        state: props.state,
        setterFunction: props.setterFunction,
        setter_timing: props.setter_timing,
        postUpdateAction: props.postUpdateAction,
        min: props.min,
        max: props.max,
        step: props.step,
        show_label_values: props.show_label_values,
        marks_step: props.marks_step,
    });

    const isVertical = props.orientation === "vertical";
    const min = props.min !== undefined ? Number(props.min) : 0;
    const max = props.max !== undefined ? Number(props.max) : 100;
    const step = props.step == null ? null : Number(props.step);

    const trackRef = useRef(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isHovered, setIsHovered] = useState(false);
    const [isFocused, setIsFocused] = useState(false);

    const decimalPlaces = step && step.toString().includes('.')
        ? step.toString().split('.')[1].length
        : 0;

    const [localValue, setLocalValue] = useState(ui_value);

    // Sync localValue with ui_value (from store) only when NOT dragging
    useEffect(() => {
        if (!isDragging) {
            setLocalValue(ui_value);
        }
    }, [ui_value, isDragging]);

    const calculateValue = useCallback((clientX, clientY) => {
        if (!trackRef.current) return localValue;
        const rect = trackRef.current.getBoundingClientRect();
        let percentage;
        if (isVertical) {
            let y = clientY - rect.top;
            y = Math.max(0, Math.min(y, rect.height));
            percentage = 1 - (y / rect.height);
        } else {
            let x = clientX - rect.left;
            x = Math.max(0, Math.min(x, rect.width));
            percentage = x / rect.width;
        }

        let rawValue = percentage * (max - min) + min;
        if (step) {
            const steps = Math.round((rawValue - min) / step);
            // Use decimalPlaces + 2 for intermediate to avoid rounding issues, then final toFixed(decimalPlaces)
            rawValue = parseFloat((steps * step + min).toFixed(decimalPlaces + 2));
            rawValue = parseFloat(rawValue.toFixed(decimalPlaces));
        }
        return Math.max(min, Math.min(rawValue, max));
    }, [isVertical, max, min, step, localValue, decimalPlaces]);

    const handlePointerDown = (e) => {
        if (e.button !== 0) return; // Only left click
        setIsDragging(true);
        const newValue = calculateValue(e.clientX, e.clientY);
        setLocalValue(newValue);
        if (newValue !== ui_value) {
            onChangeFunction(newValue);
        }
        e.preventDefault();

        // Ensure thumb gets focus-like behavior manually, though we rely on drag state
    };

    const dragRef = useRef(null);
    dragRef.current = { calculateValue, ui_value, onChangeFunction, onChangeCommittedFunction };

    useEffect(() => {
        if (!isDragging) return;

        const handlePointerMove = (e) => {
            const { calculateValue, ui_value, onChangeFunction } = dragRef.current;
            const newValue = calculateValue(e.clientX, e.clientY);
            setLocalValue(newValue);
            if (newValue !== ui_value) {
                onChangeFunction(newValue);
            }
        };

        const handlePointerUp = (e) => {
            const { calculateValue, onChangeCommittedFunction } = dragRef.current;
            setIsDragging(false);
            const newValue = calculateValue(e.clientX, e.clientY);
            setLocalValue(newValue);
            if (onChangeCommittedFunction) {
                onChangeCommittedFunction(newValue);
            }
        };

        window.addEventListener("pointermove", handlePointerMove);
        window.addEventListener("pointerup", handlePointerUp);

        return () => {
            window.removeEventListener("pointermove", handlePointerMove);
            window.removeEventListener("pointerup", handlePointerUp);
        };
    }, [isDragging]);

    // Keyboard: arrows move one step, PageUp/PageDown ten, Home/End to the
    // ends. Each key is a finished change, like releasing the pointer.
    const handleKeyDown = (e) => {
        const unit = step || (max - min) / 100;
        const moves = {
            ArrowRight: unit, ArrowUp: unit, ArrowLeft: -unit, ArrowDown: -unit,
            PageUp: unit * 10, PageDown: -unit * 10,
        };
        let next;
        if (e.key in moves) next = localValue + moves[e.key];
        else if (e.key === "Home") next = min;
        else if (e.key === "End") next = max;
        else return;
        e.preventDefault();
        next = Math.max(min, Math.min(parseFloat(next.toFixed(decimalPlaces)), max));
        if (next === localValue) return;
        setLocalValue(next);
        onChangeFunction(next);
        if (onChangeCommittedFunction) onChangeCommittedFunction(next);
    };

    const handleMouseEnter = () => {
        setIsHovered(true);
    };

    const handleMouseLeave = () => {
        setIsHovered(false);
    };

    const percentage = Math.max(0, Math.min((localValue - min) / (max - min), 1)) * 100;

    const valueLabelStr = (() => {
        let displayValue = localValue;
        if (typeof props.valueLabelFunction === "function") {
            displayValue = props.valueLabelFunction(localValue);
        }

        if (typeof props.valueLabelFormat === "function") {
            return props.valueLabelFormat(displayValue);
        } else if (typeof props.valueLabelFormat === "string") {
            return props.valueLabelFormat.replace("value", displayValue);
        }

        return displayValue;
    })();
    const valueLabelDisplay = props.valueLabelDisplay || "auto";
    const showValueLabel = valueLabelDisplay === "on" || (valueLabelDisplay === "auto" && (isHovered || isDragging || isFocused));
    const accessibleName = props["aria-label"] ?? (typeof props.label === "string" ? props.label : undefined);

    return (
        <div
            className={clsx(
                styles.container,
                props.className,
                {
                    [styles.no_padding]: props.no_padding || props.is_break_point,
                }
            )}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        >
            <div
                className={clsx(styles.sliderRoot, {
                    [styles.vertical]: isVertical,
                    [styles.horizontal]: !isVertical,
                    [styles.dragging]: isDragging
                })}
                ref={trackRef}
                onPointerDown={handlePointerDown}
            >
                <div className={styles.rail}></div>
                {props.track !== false && (
                    <div
                        className={styles.track}
                        style={{
                            ...(isVertical ? { bottom: "0%", height: `${percentage}%` } : { left: "0%", width: `${percentage}%` })
                        }}
                    ></div>
                )}

                {marks && marks.map((mark, i) => {
                    const markPercent = Math.max(0, Math.min((mark.value - min) / (max - min), 1)) * 100;
                    return (
                        <div
                            key={i}
                            className={styles.mark}
                            style={{
                                ...(isVertical ? { bottom: `${markPercent}%` } : { left: `${markPercent}%` })
                            }}
                        >
                            {mark.label && (
                                <span className={styles.markLabel}>
                                    {mark.label}
                                </span>
                            )}
                        </div>
                    );
                })}

                <div
                    className={clsx(styles.thumb, { [styles.thumbActive]: isDragging })}
                    role="slider"
                    tabIndex={0}
                    aria-label={accessibleName}
                    aria-describedby={props["aria-describedby"]}
                    aria-valuemin={min}
                    aria-valuemax={max}
                    aria-valuenow={localValue}
                    aria-valuetext={String(valueLabelStr)}
                    aria-orientation={isVertical ? "vertical" : "horizontal"}
                    onKeyDown={handleKeyDown}
                    onFocus={() => setIsFocused(true)}
                    onBlur={() => setIsFocused(false)}
                    style={{
                        ...(isVertical ? { bottom: `${percentage}%` } : { left: `${percentage}%` })
                    }}
                >
                    <div className={clsx(styles.valueLabel, styles[`location-${location}`], {
                        [styles.valueLabelOpen]: showValueLabel
                    })}>
                        <span className={styles.valueLabelLabel}>{valueLabelStr}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};
