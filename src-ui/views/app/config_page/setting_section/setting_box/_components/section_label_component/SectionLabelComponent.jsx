import styles from "./SectionLabelComponent.module.scss";

export const SectionLabelComponent = (props) => {
    return (
        <div className={styles.container}>
            <h2 className={styles.section_label}>{props.label}</h2>
            <div className={styles.section_line}></div>
        </div>
    );
};