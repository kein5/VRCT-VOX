import { useLayoutEffect, useRef } from "react";
import clsx from "clsx";
import styles from "./ConfigPage.module.scss";

import { useIsOpenedConfigPage } from "@logics_common";

import { Topbar } from "./topbar/Topbar.jsx";
import { SidebarSection } from "./sidebar_section/SidebarSection.jsx";
import { SettingSection } from "./setting_section/SettingSection.jsx";
import { SearchBar } from "./search_bar/SearchBar.jsx";

export const ConfigPage = () => {
    const { currentIsOpenedConfigPage } = useIsOpenedConfigPage();
    const root = useRef(null);
    const wasOpen = useRef(false);
    const isClosed = currentIsOpenedConfigPage.data === false;

    useLayoutEffect(() => {
        if (!isClosed) root.current?.querySelector('[aria-current="page"]')?.focus({ preventScroll: true });
        else if (wasOpen.current) document.querySelector('[data-open-settings]')?.focus({ preventScroll: true });
        wasOpen.current = !isClosed;
    }, [isClosed]);

    return (
        <div ref={root} inert={isClosed ? "" : undefined} aria-hidden={isClosed} className={clsx(styles.page, { [styles.is_closed]: isClosed })}>
            <div className={styles.container}>
                <SidebarSection />
                <div className={styles.content_wrapper}>
                    <div className={styles.main_container}>
                        <SettingSection />
                    </div>
                </div>
                <Topbar />
                <SearchBar />
            </div>
        </div>
    );
};