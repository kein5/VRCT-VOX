import clsx from "clsx";
import styles from "./StartUpProgressContainer.module.scss";

import { useInitProgress } from "@logics_common";
// VRCT-VOX's own mark: this is not the official VRCT. The English logo is used
// because the saved display language is not known until the backend answers.
import brand_icon from "@images/brand/icon-small.svg";
import brand_logo from "@images/brand/logo-en.svg";
import vrct_starting_up from "@images/vrct_starting_up.png";

export const StartUpProgressContainer = () => {
    const { currentInitProgress } = useInitProgress();

    const progress = currentInitProgress.data;
    return (
        <div className={styles.container}>
            <div className={styles.progress_bar_wrapper}>
                {[...Array(4)].map((_, index) => (
                    <div
                        key={index}
                        className={clsx(styles.progress_bar, {
                            [styles.progressed]: index < progress && progress !== 0,
                        })}
                    >
                        {index === 3
                            ?
                            <div className={styles.mark_box}>
                            <img src={brand_icon} className={styles.mark_img} alt="" />
                            </div>
                            : null
                        }
                    </div>
                ))}
            </div>
            <div className={styles.labels_wrapper}>
                <img src={vrct_starting_up} className={styles.vrct_starting_up_img} alt="Starting up..." />
                <img src={brand_logo} className={styles.brand_logo_img} alt="VRCT-VOX" />
            </div>
        </div>
    );
};
