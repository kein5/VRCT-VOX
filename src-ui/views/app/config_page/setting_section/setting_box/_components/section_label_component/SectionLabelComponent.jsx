import styles from "./SectionLabelComponent.module.scss";

// data-setting-label lets the settings search scroll to a section heading.
export const SectionLabelComponent = (props) => {
    return (
        <div className={styles.container} data-section-label
            data-setting-label={typeof props.label === "string" ? props.label : undefined}>
            <div className={styles.heading_row}>
                <h2 className={styles.section_label}>{props.label}</h2>
                <div className={styles.section_line}></div>
            </div>
            {props.desc && <p className={styles.section_desc}>{props.desc}</p>}
        </div>
    );
};
