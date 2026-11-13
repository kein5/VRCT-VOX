import styles from "./UpdatingComponent.module.scss";
import { useI18n } from "@useI18n";
import { CircularProgress } from "@common_components";
import brand_icon from "@images/brand/icon-small.svg";

export const UpdatingComponent = () => {
    const { t } = useI18n();

    return (
        <div className={styles.container}>
            <div className={styles.mark_box}>
                <img src={brand_icon} className={styles.mark_img} alt="" />
            </div>
            <div className={styles.circular_box}>
                <CircularProgress size="20rem" sx={{
                    color: "var(--primary_300_color)",
                }}/>
            </div>
            <p className={styles.label}>{t("main_page.updating")}</p>
        </div>
    );
};