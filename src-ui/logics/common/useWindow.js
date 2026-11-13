import { useEffect, useRef } from "react";
import { currentMonitor, availableMonitors, PhysicalPosition, PhysicalSize } from "@tauri-apps/api/window";
import { useStdoutToPython } from "@useStdoutToPython";
import { useStore_IsBreakPoint } from "@store";
import { useAppearance } from "@logics_configs";
import { store } from "@store";
import { isBuiltInGeometry, sizeToRestore } from "./windowGeometry.js";

// Time the backend gets to save the settings after /run/shutdown. Closing the
// window ends the app, and the shell plugin then kills the backend.
const SHUTDOWN_WAIT_MS = 2000;
let closing = null;
let releaseCloseRequest = null;

// Every way of closing the main window (the title bar button, Alt+F4, the
// taskbar) asks the backend to shut down once, waits, then destroys the window.
// Closing without it lost the settings changed in the last two seconds.
const closeAfterShutdown = (appWindow, sendToPython) => {
    if (closing) return closing;
    closing = (async () => {
        try {
            sendToPython("/run/shutdown");
        } catch (error) {
            console.error("Could not ask the backend to shut down:", error);
        }
        await new Promise(resolve => setTimeout(resolve, SHUTDOWN_WAIT_MS));
        try {
            await appWindow.destroy();
        } catch (error) {
            // Without our close-requested listener the window closes as usual.
            console.error("Could not destroy the window; closing it instead:", error);
            releaseCloseRequest?.();
            await appWindow.close();
        }
    })();
    return closing;
};

export const useWindow = () => {
    const { asyncStdoutToPython } = useStdoutToPython();
    const { currentUiScaling } = useAppearance();
    const { updateIsBreakPoint } = useStore_IsBreakPoint();

    const appWindow = store.appWindow;

    const asyncGetWindowGeometry = async () => {
        try {
            const position = await appWindow.outerPosition();
            const { x: x_pos, y: y_pos } = position;

            const size = await appWindow.outerSize();
            const { width, height } = size;

            return {
                x_pos: x_pos,
                y_pos: y_pos,
                width: width,
                height: height
            };
        } catch (err) {
            console.error("Error getting window position and size:", err);
        }
    };

    const asyncSaveWindowGeometry = async () => {
        const minimized = await appWindow.isMinimized();
        if (minimized === true) return; // don't save while the window is minimized.
        const data = await asyncGetWindowGeometry();
        asyncStdoutToPython("/set/data/main_window_geometry", data);
    };

    const restoreWindowGeometry = async (data) => {
        try {
            const monitors = await availableMonitors();
            const { x_pos, y_pos } = data;

            // ウィンドウが属するモニターを特定
            const targetMonitor = monitors.find(monitor =>
                x_pos >= monitor.position.x &&
                y_pos >= monitor.position.y &&
                x_pos < monitor.position.x + monitor.size.width &&
                y_pos < monitor.position.y + monitor.size.height
            ) || await currentMonitor();

            if (targetMonitor) {
                const { width, height } = sizeToRestore(data, targetMonitor.scaleFactor);
                // The first window also stays clear of the taskbar; a saved geometry keeps the monitor's bounds.
                const bounds = isBuiltInGeometry(data) && targetMonitor.workArea ? targetMonitor.workArea : targetMonitor;
                const { width: monitorWidth, height: monitorHeight } = bounds.size;
                const { x: monitorX, y: monitorY } = bounds.position;

                // ウィンドウのサイズをモニターサイズ内に収める
                let adjustedWidth = Math.min(parseInt(width), monitorWidth);
                let adjustedHeight = Math.min(parseInt(height), monitorHeight);

                // ウィンドウの位置をモニターの範囲内に収める
                let adjustedX = parseInt(x_pos);
                let adjustedY = parseInt(y_pos);

                // X座標がモニター左にはみ出ている場合
                if (adjustedX < monitorX) {
                    adjustedX = monitorX;
                }
                // X座標がモニター右にはみ出ている場合
                else if (adjustedX + adjustedWidth > monitorX + monitorWidth) {
                    adjustedX = monitorX + monitorWidth - adjustedWidth;
                }

                // Y座標がモニター上にはみ出ている場合
                if (adjustedY < monitorY) {
                    adjustedY = monitorY;
                }
                // Y座標がモニター下にはみ出ている場合
                else if (adjustedY + adjustedHeight > monitorY + monitorHeight) {
                    adjustedY = monitorY + monitorHeight - adjustedHeight;
                }

                await appWindow.setPosition(new PhysicalPosition(adjustedX, adjustedY));
                await appWindow.setSize(new PhysicalSize(adjustedWidth, adjustedHeight));
            } else {
                console.error("Monitor information could not be retrieved.");
            }
        } catch (err) {
            console.error("Error setting window position and size:", err);
        }
    };

    const asyncUpdateBreakPoint = async () => {
        const size = await appWindow.innerSize();
        // innerSize is in physical pixels; the breakpoint, like the CSS
        // (max-width: 800px) queries, is in CSS pixels. At 150% display
        // scaling an 800px-wide window is 1200 physical pixels.
        const width = size.width / (globalThis.devicePixelRatio || 1);
        const dynamicBreakPoint = 800 * (currentUiScaling.data / 100);
        const narrow = width <= dynamicBreakPoint;
        // Every update re-renders whatever reads IsBreakPoint, so only send changes.
        if (document.documentElement.hasAttribute("data-narrow") === narrow) return;
        updateIsBreakPoint(narrow);
        // CSS width queries miss the UI size: at 200% an 870px window lays
        // out like a 435px one. Narrow styles also key on this attribute.
        document.documentElement.toggleAttribute("data-narrow", narrow);
    };

    const asyncToggleMaximizeApp = async () => {
        const maximizeState = await appWindow.isMaximized();
        if (!maximizeState) {
            await appWindow.maximize();
        } else {
            await appWindow.unmaximize();
        }
    };

    const asyncMinimizeApp = async () => {
        await appWindow.minimize();
    };

    const asyncCloseApp = () => closeAfterShutdown(appWindow, asyncStdoutToPython);

    return {
        asyncSaveWindowGeometry,
        restoreWindowGeometry,
        asyncUpdateBreakPoint,

        asyncCloseApp,
        asyncToggleMaximizeApp,
        asyncMinimizeApp,
    };
};

// Saves the window geometry and keeps the narrow layout in step with the window.
// It is a module-level component: defined inside useWindow it was a new type on
// every render, so React remounted it each time, and the mount effect's
// IsBreakPoint update re-rendered its parent, which made it new again. That loop
// re-rendered the whole app and re-registered the window listeners about 40
// times a second while idle.
export const WindowGeometryController = () => {
    const { asyncSaveWindowGeometry, asyncUpdateBreakPoint } = useWindow();
    const { currentUiScaling } = useAppearance();
    const latest = useRef(null);
    latest.current = { asyncSaveWindowGeometry, asyncUpdateBreakPoint };

    // Also decide at startup and once the saved UI size arrives: a window that opens
    // narrow (or at a large UI size) never fires a resize event, so it kept the wide layout.
    useEffect(() => {
        asyncUpdateBreakPoint();
    }, [currentUiScaling.data]);

    useEffect(() => {
        const appWindow = store.appWindow;
        let resizeTimeout = null, moveTimeout = null;
        const unlistenResize = appWindow.onResized(() => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                latest.current.asyncSaveWindowGeometry();
                latest.current.asyncUpdateBreakPoint();
            }, 200);
        });
        const unlistenMove = appWindow.onMoved(() => {
            clearTimeout(moveTimeout);
            moveTimeout = setTimeout(() => {
                latest.current.asyncSaveWindowGeometry();
            }, 200);
        });
        return () => {
            unlistenResize.then(dispose => dispose());
            unlistenMove.then(dispose => dispose());
            clearTimeout(resizeTimeout);
            clearTimeout(moveTimeout);
        };
    }, []);

    return null;
};

// Routes a close the window system asks for (Alt+F4, the taskbar) through the
// same shutdown as the title bar button. While this listener is registered,
// Tauri leaves the closing to it.
export const WindowCloseController = () => {
    const { asyncStdoutToPython } = useStdoutToPython();
    const latest = useRef(asyncStdoutToPython);
    latest.current = asyncStdoutToPython;

    useEffect(() => {
        const appWindow = store.appWindow;
        let active = true, dispose = null;
        const release = () => {
            active = false;
            dispose?.();
            dispose = null;
        };
        appWindow.onCloseRequested(event => {
            event.preventDefault();
            closeAfterShutdown(appWindow, (...args) => latest.current(...args));
        }).then(unlisten => {
            dispose = unlisten;
            if (!active) release();
        });
        releaseCloseRequest = release;
        return () => {
            release();
            if (releaseCloseRequest === release) releaseCloseRequest = null;
        };
    }, []);

    return null;
};
