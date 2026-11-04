import styles from "./LabelComponent.module.scss";
import { _OpenWebpageButton } from "../_atoms/_open_webpage_button/_OpenWebpageButton";
import WarningSvg from "@images/warning.svg?react";
import { Description } from "../description/Description";

export const LabelComponent = (props) => {
    return (
        <div className={styles.label_component}>
            <p id={props.label_id} className={styles.label}>{props.label}</p>
            {props.desc
                ? typeof props.desc === "string" ? <Description id={props.description_id} text={props.desc} className={styles.desc} /> : <p id={props.description_id} className={styles.desc}>{props.desc}</p>
                : null
            }
            {props.add_warnings && Array.isArray(props.add_warnings) && props.add_warnings.length > 0 && (
                <div id={props.warnings_id} className={styles.warnings_section}>
                    {props.add_warnings.map((w, i) => (
                        <div className={styles.warning_item} key={i}>
                            <WarningSvg className={styles.warning_svg} aria-hidden="true" />
                            <p className={styles.warning_label}>{w.label}</p>
                        </div>
                    ))}
                </div>
            )}

            {props.webpage_url && <_OpenWebpageButton webpage_url={props.webpage_url} open_webpage_label={props.open_webpage_label} /> }
        </div>
    );
};