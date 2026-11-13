// The geometry the backend sends until the user has moved or resized the window
// (MAIN_WINDOW_GEOMETRY in src-python/config.py).
export const BUILT_IN_GEOMETRY = { x_pos: 0, y_pos: 0, width: 870, height: 654 };

export const isBuiltInGeometry = geometry =>
    Object.keys(BUILT_IN_GEOMETRY).every(key => parseInt(geometry?.[key]) === BUILT_IN_GEOMETRY[key]);

// The window's size is saved and restored in physical pixels, but the built-in size
// is meant in CSS pixels. At 125% display scaling, 870x654 physical pixels are
// 696x523 CSS pixels: the first window opened in the narrow layout, with the
// sidebar's language readout cut off. While the geometry is still the built-in one,
// the size is multiplied by the monitor's scale factor. The window then saves its
// real size, so this applies once.
export const sizeToRestore = (geometry, scaleFactor) => {
    const scale = isBuiltInGeometry(geometry) && scaleFactor > 1 ? scaleFactor : 1;
    return {
        width: Math.round(parseInt(geometry.width) * scale),
        height: Math.round(parseInt(geometry.height) * scale),
    };
};
