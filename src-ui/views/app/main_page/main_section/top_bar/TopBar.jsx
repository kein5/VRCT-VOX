import styles from "./TopBar.module.scss";

import { SidebarCompactModeButton } from "./sidebar_compact_mode_button/SidebarCompactModeButton";
import { RightSideComponents } from "./right_side_components/RightSideComponents";
import { StopActions } from "../../../others/stop_actions/StopActions";

// Stop and mute lead the bar: they are what a conversation needs within reach,
// and they keep the same place in every window size. The window and VRChat
// toggles sit behind one menu on the right.
export const TopBar = () => {
    return (
        <div className={styles.container}>
            <div className={styles.leading}>
                <SidebarCompactModeButton />
                <StopActions classes={styles} />
            </div>
            <RightSideComponents />
        </div>
    );
};
