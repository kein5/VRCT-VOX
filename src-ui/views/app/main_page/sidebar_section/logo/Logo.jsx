import styles from "./Logo.module.scss";
import { useIsMainPageCompactMode } from "@logics_main";

export const Logo = () => <div className={styles.container}><LogoBox /></div>;

export const LogoBox = () => {
    const { currentIsMainPageCompactMode } = useIsMainPageCompactMode();
    return <div className={styles.wordmark} aria-label="VRCT-VOX" translate="no">
        {!currentIsMainPageCompactMode.data && <span className={styles.prefix}>VRCT</span>}
        <span className={styles.name}>VOX</span>
    </div>;
};
