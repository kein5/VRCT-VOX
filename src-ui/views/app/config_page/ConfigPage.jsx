import { useEffect, useLayoutEffect, useRef } from "react";
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

    // Opening settings moves focus to the selected tab for keyboard users.
    // WebKit can draw that focus ring after a mouse click too, so the sidebar
    // hides it while the last input was a pointer.
    useEffect(() => {
        const set = input => () => { document.documentElement.dataset.lastInput = input; };
        const pointer = set("pointer"), keyboard = set("keyboard");
        window.addEventListener("pointerdown", pointer, true);
        window.addEventListener("keydown", keyboard, true);
        return () => {
            window.removeEventListener("pointerdown", pointer, true);
            window.removeEventListener("keydown", keyboard, true);
        };
    }, []);

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
                    <Topbar />
                </div>
                <SearchBar />
            </div>
        </div>
    );
};