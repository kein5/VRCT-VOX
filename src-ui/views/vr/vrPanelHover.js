const HOVER_TARGET = "button, [data-vr-hoverable]";

// A stationary laser still needs a fresh hit test when a list scrolls or a
// picker is replaced. All invalidations share one frame, with no idle timer.
export const trackVrPointerHover = (root) => {
    let pointer = null, hovered = null, frame = null, disposed = false;
    const update = (target) => {
        if (target === hovered) return;
        hovered?.removeAttribute("data-vr-hover");
        target?.setAttribute("data-vr-hover", "");
        hovered = target;
    };
    const invalidate = () => {
        if (disposed || !pointer || frame !== null) return;
        frame = requestAnimationFrame(() => {
            frame = null;
            const element = document.elementFromPoint(pointer.x, pointer.y);
            const target = element?.closest(HOVER_TARGET) ?? null;
            update(target && root.contains(target) && !target.closest("[inert]") ? target : null);
        });
    };
    const mutations = new MutationObserver(invalidate);
    // Exclude data-vr-hover: our own feedback must not schedule more work.
    mutations.observe(root, { subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ["class", "style", "hidden", "inert", "disabled"] });
    // FontFamilyController writes inherited styles on <html>, outside the atlas.
    for (const ancestor of [document.documentElement, document.body]) {
        if (ancestor) mutations.observe(ancestor, { attributes: true, attributeFilter: ["class", "style", "lang", "dir"] });
    }
    const resize = new ResizeObserver(invalidate);
    resize.observe(root);
    for (const region of root.querySelectorAll("[data-vr-region]")) resize.observe(region);
    root.addEventListener("scroll", invalidate, true);
    window.addEventListener("resize", invalidate);
    document.fonts?.addEventListener("loadingdone", invalidate);

    const cancelFrame = () => {
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
    };
    return {
        setPointer: (position) => {
            if (disposed) return;
            pointer = position;
            if (pointer) invalidate();
            else { cancelFrame(); update(null); }
        },
        dispose: () => {
            disposed = true;
            pointer = null;
            cancelFrame();
            mutations.disconnect();
            resize.disconnect();
            root.removeEventListener("scroll", invalidate, true);
            window.removeEventListener("resize", invalidate);
            document.fonts?.removeEventListener("loadingdone", invalidate);
            update(null);
        },
    };
};
