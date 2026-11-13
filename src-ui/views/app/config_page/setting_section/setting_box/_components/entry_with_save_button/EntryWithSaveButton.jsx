import styles from "./EntryWithSaveButton.module.scss";
import { _Entry } from "../_atoms/_entry/_Entry";

// Saved from the config page top bar; Enter saves this one field.
export const EntryWithSaveButton = (props) => {
    const onChangeFunction = (e) => {
        if (props.state === "pending") return;
        props.onChangeFunction?.(e.target.value);
    };
    const saveFunction = () => {
        props.saveFunction();
    };
    const is_disabled = props.state === "pending";

    const handleEnterPressed = () => {
        if (is_disabled) return;
        saveFunction();
    };

    return (
        <div className={styles.container}>
            <_Entry label={props.label} width={props.width} type={props.type} min={props.min} max={props.max} step={props.step} onChange={onChangeFunction} onEnterPressed={handleEnterPressed} ui_variable={props.variable} readOnly={is_disabled} aria-busy={is_disabled} aria-disabled={is_disabled} aria-describedby={props["aria-describedby"]}/>
        </div>
    );
};