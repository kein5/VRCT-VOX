import { useI18n } from "@useI18n";
import { splitDescription } from "../../../../../../../logics/configs/descriptionSplit";
import styles from "./Description.module.scss";

// General description role (DESIGN.md): one visible sentence, the rest under "詳細".
export const Description = ({ text, className }) => {
    const { t } = useI18n();
    const [first, rest] = splitDescription(text);
    if (!rest) return <p className={className}>{first}</p>;
    return <div className={styles.description}>
        <p className={className}>{first}</p>
        <details className={styles.more}>
            <summary>{t("voice_ui.details")}</summary>
            <p className={className}>{rest}</p>
        </details>
    </div>;
};
