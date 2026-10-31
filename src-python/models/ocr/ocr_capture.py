"""Capture backend facade for OCR: picks the desktop window vs OpenVR by SteamVR status.

The desktop window backend is HWND/PrintWindow on Windows and X11/XWayland
(ocr_capture_x11.py) on Linux.

Contract: get() returns a BGR ndarray or None. It never raises. The
facade rechecks SteamVR periodically so the backend follows the user
launching/closing SteamVR while VRCT is running. When the VR read gives
nothing (VRChat is not the SteamVR scene, or the read failed) it falls back
to the desktop window until the next recheck.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

import numpy as np

from ..process_check import isProcessRunning

from .ocr_capture_hwnd import HwndCapture, _find_vrchat_hwnd, isFrameBlank
from .ocr_capture_openvr import OpenVRMirrorCapture
from .ocr_capture_x11 import X11WindowCapture

try:
    from utils import errorLogging, printLog
except Exception:  # pragma: no cover
    def errorLogging():
        import traceback
        print(traceback.format_exc())

    def printLog(*args, **kwargs):
        print(*args, **kwargs)


_STEAMVR_RECHECK_INTERVAL_SEC = 5.0

# probeCapture() results. The pipeline turns the last two into OCR_DISABLED_*.
CAPTURE_OK = "ok"
CAPTURE_WINDOW_NOT_FOUND = "window_not_found"
CAPTURE_UNAVAILABLE = "capture_unavailable"


def _isSteamvrRunning() -> bool:
    return isProcessRunning("vrmonitor.exe" if os.name == "nt" else "vrmonitor")


def _windowCapture(window_title: str):
    """(backend name, capture) for the desktop window on this platform."""
    if sys.platform == "win32":
        return OcrCapture.BACKEND_HWND, HwndCapture(window_title=window_title)
    return OcrCapture.BACKEND_X11, X11WindowCapture(window_title=window_title)


def probeCapture(window_title: str) -> str:
    """Can the window be read right now? Opens and closes everything it uses.

    Run before the worker starts so the toggle can say why reading cannot
    begin (no X11 / XWayland session, or VRChat is not running) instead of
    starting a loop that silently reads nothing.
    """
    if sys.platform == "win32":
        if _isSteamvrRunning() and OpenVRMirrorCapture().isAvailable():
            return CAPTURE_OK
        return CAPTURE_OK if _find_vrchat_hwnd(window_title) is not None else CAPTURE_WINDOW_NOT_FOUND
    capture = X11WindowCapture(window_title=window_title)
    try:
        if not capture.isAvailable():
            return CAPTURE_UNAVAILABLE
        return CAPTURE_OK if capture.findWindow() is not None else CAPTURE_WINDOW_NOT_FOUND
    except Exception:
        errorLogging()
        return CAPTURE_UNAVAILABLE
    finally:
        capture.close()


class OcrCapture:
    """Facade that returns the current VRChat frame using the best backend."""

    BACKEND_HWND = "hwnd"
    BACKEND_X11 = "x11"
    BACKEND_OPENVR = "openvr_mirror"
    BACKEND_NONE = "none"

    def __init__(self, window_title: str = "VRChat") -> None:
        self._window_backend, self._window = _windowCapture(window_title)
        self._openvr: Optional[OpenVRMirrorCapture] = None
        self._backend = self.BACKEND_NONE
        # 実際にフレームが取れた経路。VRとデスクトップを5秒ごとに試し直すので、
        # 試した経路ではなく取れた経路が変わったときだけログに出す。
        self._source = self.BACKEND_NONE
        self._last_check = 0.0

    def _selectBackend(self, force: bool = False) -> str:
        now = time.monotonic()
        if not force and (now - self._last_check) < _STEAMVR_RECHECK_INTERVAL_SEC:
            return self._backend
        self._last_check = now

        want_openvr = _isSteamvrRunning()
        if want_openvr:
            if self._openvr is None:
                candidate = OpenVRMirrorCapture()
                if candidate.isAvailable():
                    self._openvr = candidate
            if self._openvr is not None and self._openvr.isAvailable():
                self._backend = self.BACKEND_OPENVR
                return self._backend
        # Fall back to the desktop window
        if self._openvr is not None:
            try:
                self._openvr.close()
            except Exception:
                pass
            self._openvr = None
        self._backend = self._window_backend if self._window.isAvailable() else self.BACKEND_NONE
        return self._backend

    def _noteSource(self, backend: str) -> None:
        if self._source != backend:
            printLog(f"OCR capture backend -> {backend}")
            self._source = backend

    @property
    def backend(self) -> str:
        return self._backend

    def get(self) -> Optional[np.ndarray]:
        backend = self._selectBackend()
        try:
            if backend == self.BACKEND_OPENVR and self._openvr is not None:
                frame = self._openvr.capture()
                if frame is not None:
                    # The compositor only hands back a texture when it is actually
                    # presenting, so an all-black frame here is a legitimately dark
                    # scene (night world, loading screen) rather than a dead
                    # surface. Only reject a truly uniform frame.
                    # Exact and cheap (12 ms at 2575x1455; np.var on the whole frame took 170 ms).
                    if frame.min() == frame.max():
                        return None
                    self._noteSource(self.BACKEND_OPENVR)
                    return frame
                # VRChat is not the SteamVR scene (desktop mode, SteamVR Home)
                # or the VR read failed: use the desktop window until the
                # next recheck instead of reading nothing.
                self._backend = self._window_backend if self._window.isAvailable() else self.BACKEND_NONE
                backend = self._backend
            if backend == self._window_backend:
                frame = self._window.capture()
                # A minimized or occluded window keeps returning a stale black
                # buffer, so the stricter thresholds earn their keep here.
                if isFrameBlank(frame):
                    return None
                self._noteSource(self._window_backend)
                return frame
        except Exception:
            errorLogging()
        return None

    def close(self) -> None:
        try:
            self._window.close()
        except Exception:
            pass
        if self._openvr is not None:
            try:
                self._openvr.close()
            except Exception:
                pass
            self._openvr = None
        self._backend = self.BACKEND_NONE
        self._source = self.BACKEND_NONE
