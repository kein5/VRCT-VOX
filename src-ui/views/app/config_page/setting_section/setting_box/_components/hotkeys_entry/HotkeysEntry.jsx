import styles from "./HotkeysEntry.module.scss";
import { _Entry } from "../_atoms/_entry/_Entry";
import { useState, useRef, useEffect } from "react";
import DeleteSvg from "@images/cancel.svg?react";
import clsx from "clsx";
import { useI18n } from "@useI18n";

export const HotkeysEntry = (props) => {
    const { t } = useI18n();
    const [isAcceptingInput, setIsAcceptingInput] = useState(false);
    const [displayValue, setDisplayValue] = useState("");
    const committedDisplayValueRef = useRef("");
    const lastKeyRef = useRef(null);
    const isModifierOnlyRef = useRef(false);
    const entryRef = useRef(null);
    const pressedKeys = useRef(new Set());
    const keysRef = useRef([]);
    const editVersion = useRef(0);

    useEffect(() => {
        const hotkey = props.value[props.hotkey_id];
        const display_value = hotkey ? hotkey.join(" + ") : "";
        committedDisplayValueRef.current = display_value;
        if (!isAcceptingInput) setDisplayValue(display_value);
    }, [props.value, props.hotkey_id, isAcceptingInput]);


    const updateHotkeys = async (keys) => {
        const version = ++editVersion.current;
        entryRef.current.blur();
        const result = await props.setHotkeys({ [props.hotkey_id]: keys });
        if (result === false && editVersion.current === version) setDisplayValue(committedDisplayValueRef.current);
    };

    // Key names as stored and as the shortcut parsers read them ("Ctrl", "Q").
    // Space is spelled out: " " cannot be joined into "Control+Space". A digit
    // is taken from the key itself, since Shift turns "1" into "!" on keydown
    // but not on a keyup after Shift was released.
    const processKey = ({ key, code }) => {
        if (key === " " || code === "Space") return "Space";
        if (/^[a-zA-Z]$/.test(key)) return key.toUpperCase();
        if (/^Digit[0-9]$/.test(code ?? "")) return code.slice(-1);
        if (key === "Meta") return "Super";
        return key;
    };

    const handleKeyInput = (event) => {
        const keys = [];
        const nonModifierKeys = [];

        ["Ctrl", "Shift", "Alt", "Meta"].forEach((modKey) => {
            if (event[`${modKey.toLowerCase()}Key`] && !keys.includes(modKey)) {
                let register_mod_key =  (modKey === "Meta") ? "Super" : modKey;
                keys.push(register_mod_key);
            }
        });

        const key = processKey(event);
        if (!["Control", "Shift", "Alt", "Meta"].includes(event.key)) {
            keys.push(key);
            nonModifierKeys.push(key);
        }

        if (!pressedKeys.current.has(key)) {
            pressedKeys.current.add(key);
        }

        keysRef.current = keys;
        setDisplayValue(keys.join(" + "));
        isModifierOnlyRef.current = nonModifierKeys.length === 0;
    };

    const handleKeyDown = (event) => {
        if (event.key === "Tab" || event.key === "Escape") {
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
            }
            cancelInput();
            return;
        }
        event.preventDefault();
        if (lastKeyRef.current === event.key) return;

        lastKeyRef.current = event.key;
        handleKeyInput(event);
    };

    const handleKeyUp = (event) => {
        if (event.key === "Tab" || event.key === "Escape") return;
        lastKeyRef.current = null;

        const key = processKey(event);
        if (!pressedKeys.current.has(key)) return;
        pressedKeys.current.delete(key);

        if (isModifierOnlyRef.current) {
            setDisplayValue("");
        }

        if (pressedKeys.current.size === 0) {
            const hasNonModifierKeys = keysRef.current.some(
                (key) => !["Ctrl", "Shift", "Alt", "Super"].includes(key)
            );
            if (hasNonModifierKeys) {
                updateHotkeys(keysRef.current);
            } else {
                const display_value = props.value[props.hotkey_id] ? props.value[props.hotkey_id].join(" + ") : "";
                setDisplayValue(display_value);
            }
        }
    };

    const cancelInput = () => {
        pressedKeys.current.clear();
        keysRef.current = [];
        lastKeyRef.current = null;
        isModifierOnlyRef.current = false;
        setDisplayValue(committedDisplayValueRef.current);
    };

    const handleBlur = () => {
        setIsAcceptingInput(false);
        cancelInput();
    };

    const handleFocus = () => {
        editVersion.current++;
        setIsAcceptingInput(true);
        setDisplayValue("");
    };

    const handleDelete = () => {
        updateHotkeys(null);
        setDisplayValue("");
    };

    const is_pending = props.state === "pending";
    const is_assigned = !!props.value[props.hotkey_id]?.length;
    return (
        <div className={styles.container}>
            {is_pending && <span className={styles.loader}></span>}
            <_Entry
                aria-describedby={props["aria-describedby"]}
                aria-label={props.label}
                ref={entryRef}
                onFocus={handleFocus}
                onBlur={handleBlur}
                onKeyDown={handleKeyDown}
                onKeyUp={handleKeyUp}
                placeholder={t(isAcceptingInput ? "config_page.hotkeys.input_placeholder" : "config_page.hotkeys.unassigned_placeholder")}
                ui_variable={displayValue}
                width="20rem"
                is_activated={isAcceptingInput}
                is_disabled={is_pending}
                readOnly
            />
            {/* Nothing to clear while no key is set. */}
            <button type="button" aria-label={t("quick_chat.clear_shortcut", { action: props.label })} disabled={is_pending || !is_assigned} className={clsx(styles.delete_button, { [styles.is_pending]: is_pending })} onClick={handleDelete}>
                <DeleteSvg className={styles.delete_svg}/>
            </button>
        </div>
    );
};
