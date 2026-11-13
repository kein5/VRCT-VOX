import { useI18n } from "@useI18n";
import { splitDescription } from "../../../../../../../logics/configs/descriptionSplit";
import styles from "./Description.module.scss";

// General description role (DESIGN.md): one visible sentence, the rest under "詳細".
// `id` lets a control point at it with aria-describedby; `fold={false}` keeps
// text that changes as you type (a character count) in view.
export const Description = ({ text, className, id, fold = true }) => {
    const { t } = useI18n();
    const [first, rest] = fold ? splitDescription(text) : [text, ""];
    if (!rest) return <p id={id} className={className}>{first}</p>;
    return <div id={id} className={styles.description}>
        <p className={className}>{first}</p>
        <details className={styles.more}>
            <summary>{t("voice_ui.details")}</summary>
            <p className={className}>{rest}</p>
        </details>
    </div>;
};
