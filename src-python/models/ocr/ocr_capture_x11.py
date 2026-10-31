"""X11 / XWayland capture of the VRChat window by title (Linux).

VRChat under Proton is an X11 client, so on KDE Plasma Wayland it is an
XWayland window and the X protocol can read it. XGetImage on the window
itself reads the window's own contents, not the screen, so VRCT-VOX or
another window on top does not end up in the frame (the same property
PrintWindow gives on Windows). Rootless XWayland redirects every toplevel to
an offscreen pixmap, which is what XGetImage reads; on a plain X11 session
with a compositor the same holds, and without one an occluded window reads
as whatever covers it, which isFrameBlank or the chatbox filter then drops.

Dependency: libX11 through ctypes. It is part of every X11 or XWayland
session and already loaded by the GTK/WebKit UI, so it adds nothing to the
AppImage; python-xlib or mss would add a package for the same few calls.

Xlib's default error handler calls exit(). A window can vanish between
finding it and reading it (BadWindow) or be unmapped (BadMatch), so this
module installs a recording handler before each batch of calls and syncs to
collect errors. Where libX11 >= 1.7 offers XSetIOErrorExitHandler, losing
the X server marks the display dead instead of exiting.

Thread contract: the Display is opened, used and closed on the OCR worker
thread only (OcrCapture is constructed there).

Not covered: native Wayland windows (PROTON_ENABLE_WAYLAND=1, or a Wayland
VRChat client). Those need the xdg-desktop-portal ScreenCast path; see
src-python/docs/details/ocr-linux-capture.md.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from typing import List, Optional, Tuple

import numpy as np

try:
    from utils import errorLogging, printLog
except Exception:  # pragma: no cover
    def errorLogging():
        import traceback
        print(traceback.format_exc())

    def printLog(*args, **kwargs):
        print(*args, **kwargs)


_VRCHAT_WINDOW_TITLE = "VRChat"
_ZPIXMAP = 2
_ALL_PLANES = 0xFFFFFFFFFFFFFFFF
_IS_VIEWABLE = 2
_ANY_PROPERTY_TYPE = 0
_SUCCESS = 0
_MAX_TREE_DEPTH = 3

Window = ctypes.c_ulong
Atom = ctypes.c_ulong


class _XErrorEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("display", ctypes.c_void_p), ("resourceid", ctypes.c_ulong),
                ("serial", ctypes.c_ulong), ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte),
                ("minor_code", ctypes.c_ubyte)]


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", Window), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
                ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
                ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
                ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


class _XImage(ctypes.Structure):
    pass


_DESTROY = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_XImage))


class _XImageFuncs(ctypes.Structure):
    _fields_ = [("create_image", ctypes.c_void_p), ("destroy_image", _DESTROY), ("get_pixel", ctypes.c_void_p),
                ("put_pixel", ctypes.c_void_p), ("sub_image", ctypes.c_void_p), ("add_pixel", ctypes.c_void_p)]


_XImage._fields_ = [("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int),
                    ("format", ctypes.c_int), ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
                    ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int),
                    ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int),
                    ("bits_per_pixel", ctypes.c_int), ("red_mask", ctypes.c_ulong),
                    ("green_mask", ctypes.c_ulong), ("blue_mask", ctypes.c_ulong), ("obdata", ctypes.c_void_p),
                    ("f", _XImageFuncs)]

_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_XErrorEvent))
_IO_EXIT_HANDLER = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


class _State:
    lib = None
    loaded = False
    last_error = 0
    dead_displays: set = set()


def _onError(_display, event):
    try:
        _State.last_error = int(event.contents.error_code) or 1
    except Exception:
        _State.last_error = 1
    return 0


def _onIoExit(display, _data):
    _State.dead_displays.add(display)


# Kept at module level: ctypes callbacks must outlive every call that can fire them.
_error_handler = _ERROR_HANDLER(_onError)
_io_exit_handler = _IO_EXIT_HANDLER(_onIoExit)


def _load():
    if _State.loaded:
        return _State.lib
    _State.loaded = True
    if not sys.platform.startswith("linux"):
        return None
    name = ctypes.util.find_library("X11") or "libX11.so.6"
    try:
        lib = ctypes.CDLL(name)
    except OSError:
        return None
    lib.XInitThreads.restype = ctypes.c_int
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    lib.XDefaultRootWindow.restype = Window
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    lib.XInternAtom.restype = Atom
    lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.XGetWindowProperty.restype = ctypes.c_int
    lib.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, Window, Atom, ctypes.c_long, ctypes.c_long, ctypes.c_int, Atom,
        ctypes.POINTER(Atom), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    lib.XQueryTree.restype = ctypes.c_int
    lib.XQueryTree.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(Window), ctypes.POINTER(Window),
                               ctypes.POINTER(ctypes.POINTER(Window)), ctypes.POINTER(ctypes.c_uint)]
    lib.XGetWindowAttributes.restype = ctypes.c_int
    lib.XGetWindowAttributes.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(_XWindowAttributes)]
    lib.XGetImage.restype = ctypes.POINTER(_XImage)
    lib.XGetImage.argtypes = [ctypes.c_void_p, Window, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                              ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
    lib.XFree.argtypes = [ctypes.c_void_p]
    lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XSetErrorHandler.restype = ctypes.c_void_p
    lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    lib.XInitThreads()
    _State.lib = lib
    return lib


def _setIoExitHandler(lib, display) -> None:
    setter = getattr(lib, "XSetIOErrorExitHandler", None)
    if setter is None:
        return
    setter.restype = None
    setter.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    setter(display, ctypes.cast(_io_exit_handler, ctypes.c_void_p), None)


def frameFromXImage(width: int, height: int, bytes_per_line: int, bits_per_pixel: int,
                    red_mask: int, blue_mask: int, byte_order: int, data: bytes) -> Optional[np.ndarray]:
    """32-bit TrueColor ZPixmap bytes -> BGR ndarray. Other layouts -> None."""
    if bits_per_pixel != 32 or width <= 0 or height <= 0 or bytes_per_line < width * 4:
        return None
    if len(data) < bytes_per_line * height:
        return None
    rows = np.frombuffer(data, dtype=np.uint8, count=bytes_per_line * height).reshape(height, bytes_per_line)
    pixels = rows[:, :width * 4].reshape(height, width, 4)
    # Byte order in memory: LSBFirst (0) with red in 0xff0000 is B,G,R,X.
    if (red_mask, blue_mask) == (0xFF0000, 0xFF):
        order = (0, 1, 2) if byte_order == 0 else (3, 2, 1)
    elif (red_mask, blue_mask) == (0xFF, 0xFF0000):
        order = (2, 1, 0) if byte_order == 0 else (1, 2, 3)
    else:
        return None
    return np.ascontiguousarray(pixels[:, :, list(order)])


def _matches(title: str, needle: str) -> int:
    """0 exact, 1 substring, -1 no match (case-insensitive substring like the Windows path)."""
    if not title:
        return -1
    if title == needle:
        return 0
    return 1 if needle.lower() in title.lower() else -1


def _processName(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8", errors="replace") as stream:
            return stream.read().strip().lower()
    except OSError:
        return ""


class X11WindowCapture:
    """Capture an X11/XWayland window by title. capture() never raises."""

    def __init__(self, window_title: str = _VRCHAT_WINDOW_TITLE, display_name: Optional[str] = None) -> None:
        self.window_title = window_title or _VRCHAT_WINDOW_TITLE
        self._display_name = display_name
        self._display = None
        self._window: Optional[int] = None
        self._atoms = {}
        self._failure_logged = False

    # ---- availability ----------------------------------------------------
    def isAvailable(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        if not (self._display_name or os.environ.get("DISPLAY")):
            return False
        return _load() is not None and self._open() is not None

    def _open(self):
        if self._display is not None and self._display not in _State.dead_displays:
            return self._display
        self._display = None
        lib = _load()
        if lib is None:
            return None
        name = self._display_name.encode() if self._display_name else None
        display = lib.XOpenDisplay(name)
        if not display:
            return None
        _setIoExitHandler(lib, display)
        self._display = display
        self._atoms = {}
        self._window = None
        return display

    def _atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = _State.lib.XInternAtom(self._display, name.encode(), 1)
        return self._atoms[name]

    def _begin(self) -> None:
        _State.lib.XSetErrorHandler(ctypes.cast(_error_handler, ctypes.c_void_p))
        _State.last_error = 0

    def _failed(self) -> bool:
        _State.lib.XSync(self._display, 0)
        return _State.last_error != 0 or self._display in _State.dead_displays

    # ---- properties ------------------------------------------------------
    def _property(self, window: int, name: str, max_items: int = 1 << 16) -> Tuple[int, int, bytes]:
        atom = self._atom(name)
        if not atom:
            return (0, 0, b"")
        actual_type, actual_format = Atom(), ctypes.c_int()
        items, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        status = _State.lib.XGetWindowProperty(
            self._display, window, atom, 0, max_items, 0, _ANY_PROPERTY_TYPE, ctypes.byref(actual_type),
            ctypes.byref(actual_format), ctypes.byref(items), ctypes.byref(after), ctypes.byref(data))
        if status != _SUCCESS or not data.value:
            return (0, 0, b"")
        try:
            unit = {8: 1, 16: ctypes.sizeof(ctypes.c_short), 32: ctypes.sizeof(ctypes.c_long)}.get(actual_format.value, 0)
            raw = ctypes.string_at(data.value, unit * items.value) if unit else b""
        finally:
            _State.lib.XFree(data)
        return (actual_format.value, items.value, raw)

    def _windows(self, window: int, name: str) -> List[int]:
        fmt, count, raw = self._property(window, name)
        if fmt != 32 or not count:
            return []
        return list((ctypes.c_ulong * count).from_buffer_copy(raw))

    def _title(self, window: int) -> str:
        for name in ("_NET_WM_NAME", "WM_NAME"):
            fmt, _count, raw = self._property(window, name, 1024)
            if fmt == 8 and raw:
                return raw.decode("utf-8", errors="replace").rstrip("\0")
        return ""

    def _classes(self, window: int) -> List[str]:
        fmt, _count, raw = self._property(window, "WM_CLASS", 256)
        if fmt != 8:
            return []
        return [part.decode("utf-8", errors="replace").lower() for part in raw.split(b"\0") if part]

    def _pid(self, window: int) -> int:
        fmt, count, raw = self._property(window, "_NET_WM_PID", 1)
        if fmt != 32 or not count:
            return 0
        return int(ctypes.c_ulong.from_buffer_copy(raw).value)

    def _children(self, window: int) -> List[int]:
        root, parent = Window(), Window()
        children, count = ctypes.POINTER(Window)(), ctypes.c_uint()
        if not _State.lib.XQueryTree(self._display, window, ctypes.byref(root), ctypes.byref(parent),
                                     ctypes.byref(children), ctypes.byref(count)):
            return []
        try:
            return [children[i] for i in range(count.value)]
        finally:
            if children:
                _State.lib.XFree(children)

    def _candidates(self) -> List[int]:
        root = _State.lib.XDefaultRootWindow(self._display)
        managed = self._windows(root, "_NET_CLIENT_LIST")
        if managed:
            return managed
        # No EWMH window manager: walk the tree (titles live on the client window,
        # which a reparenting WM puts one or two levels below the root).
        found, frontier = [], [(root, 0)]
        while frontier:
            window, depth = frontier.pop()
            if depth:
                found.append(window)
            if depth < _MAX_TREE_DEPTH:
                frontier.extend((child, depth + 1) for child in self._children(window))
        return found

    def _viewable(self, window: int) -> Optional[_XWindowAttributes]:
        attributes = _XWindowAttributes()
        if not _State.lib.XGetWindowAttributes(self._display, window, ctypes.byref(attributes)):
            return None
        if attributes.map_state != _IS_VIEWABLE or attributes.width <= 1 or attributes.height <= 1:
            return None
        return attributes

    def findWindow(self) -> Optional[int]:
        """Best match: exact title, then substring, then WM_CLASS / process name."""
        if self._open() is None:
            return None
        self._begin()
        needle = self.window_title
        bare = needle.lower()[:-4] if needle.lower().endswith(".exe") else needle.lower()
        ranked = []
        try:
            for window in self._candidates():
                rank = _matches(self._title(window), needle)
                if rank < 0:
                    names = self._classes(window)
                    pid = self._pid(window)
                    if pid:
                        names.append(_processName(pid))
                    if any(name in (bare, bare + ".exe") for name in names):
                        rank = 2
                if rank >= 0 and self._viewable(window) is not None:
                    ranked.append((rank, window))
        except Exception:
            errorLogging()
            return None
        if self._failed() and not ranked:
            return None
        return min(ranked)[1] if ranked else None

    # ---- capture ---------------------------------------------------------
    def _grab(self, window: int) -> Optional[np.ndarray]:
        attributes = self._viewable(window)
        if attributes is None:
            return None
        image = _State.lib.XGetImage(self._display, window, 0, 0, attributes.width, attributes.height,
                                     _ALL_PLANES, _ZPIXMAP)
        if not image:
            return None
        try:
            ximage = image.contents
            size = ximage.bytes_per_line * ximage.height
            data = ctypes.string_at(ximage.data, size) if ximage.data else b""
            return frameFromXImage(ximage.width, ximage.height, ximage.bytes_per_line, ximage.bits_per_pixel,
                                   ximage.red_mask, ximage.blue_mask, ximage.byte_order, data)
        finally:
            image.contents.f.destroy_image(image)

    def capture(self) -> Optional[np.ndarray]:
        if self._open() is None:
            return None
        window = self._window or self.findWindow()
        if window is None:
            return None
        self._begin()
        try:
            frame = self._grab(window)
        except Exception:
            if not self._failure_logged:
                errorLogging()
                self._failure_logged = True
            frame = None
        if self._failed() or frame is None:
            # Gone, unmapped or resized mid-read: look the window up again next tick.
            self._window = None
            if self._display in _State.dead_displays:
                self.close()
            return None
        self._window = window
        self._failure_logged = False
        return frame

    def close(self) -> None:
        display, self._display = self._display, None
        self._window = None
        self._atoms = {}
        if display is not None and _State.lib is not None and display not in _State.dead_displays:
            try:
                _State.lib.XCloseDisplay(display)
            except Exception:
                pass
