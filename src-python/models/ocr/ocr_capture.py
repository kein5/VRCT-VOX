"""Capture backend facade for OCR: picks the desktop window vs OpenVR by SteamVR status.

The desktop window backend is HWND/PrintWindow on Windows and X11/XWayland
(ocr_capture_x11.py) on Linux. The OpenVR mirror is read through D3D11 on
Windows and OpenGL on Linux. On Linux, a window the user shares through the
desktop's ScreenCast portal (ocr_capture_portal.py) is read instead of the one
found by name for as long as it is shared; nothing here starts that sharing.

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
from .ocr_capture_portal import SharedWindowCapture
from .ocr_capture_x11 import X11WindowCapture
from .ocr_failure import OcrFailureLog

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


class SharedWindowEnded(RuntimeError):
    """The window the user shared is gone and none can be read by name in its place."""


def availableCaptureSources() -> list[str]:
    return ["window", "vr"] if OpenVRMirrorCapture().isAvailable() else ["window"]


def _isSteamvrRunning() -> bool:
    return isProcessRunning("vrmonitor.exe" if os.name == "nt" else "vrmonitor")


def _windowCapture(window_title: str):
    """(backend name, capture) for the desktop window on this platform."""
    if sys.platform == "win32":
        return OcrCapture.BACKEND_HWND, HwndCapture(window_title=window_title)
    return OcrCapture.BACKEND_X11, X11WindowCapture(window_title=window_title)


def _sharedWindow() -> Optional[SharedWindowCapture]:
    """The reader for a window shared through the portal; only Linux has one."""
    return SharedWindowCapture() if sys.platform.startswith("linux") else None


def probeCapture(window_title: str) -> str:
    """Can the window be read right now? Opens and closes everything it uses.

    Run before the worker starts so the toggle can say why reading cannot
    begin (no X11 / XWayland session, or VRChat is not running) instead of
    starting a loop that silently reads nothing. A window the user is sharing
    counts as readable; this never asks for one.
    """
    # The headset view needs no window: VRChat's desktop window may be minimized in VR.
    if _isSteamvrRunning() and OpenVRMirrorCapture().isAvailable():
        return CAPTURE_OK
    if sys.platform == "win32":
        return CAPTURE_OK if _find_vrchat_hwnd(window_title) is not None else CAPTURE_WINDOW_NOT_FOUND
    shared = _sharedWindow()
    if shared is not None and shared.isActive():
        return CAPTURE_OK
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
    BACKEND_PORTAL = "portal"
    BACKEND_OPENVR = "openvr_mirror"
    BACKEND_NONE = "none"

    def __init__(self, window_title: str = "VRChat") -> None:
        self._window_backend, self._window = _windowCapture(window_title)
        self._shared = _sharedWindow()
        # None, "active" while the shared window is read, "ended" once it is gone
        # and no window found by name has taken its place.
        self._shared_state: Optional[str] = None
        self._openvr: Optional[OpenVRMirrorCapture] = None
        self._backend = self.BACKEND_NONE
        # 実際にフレームが取れた経路。VRとデスクトップを5秒ごとに試し直すので、
        # 試した経路ではなく取れた経路が変わったときだけログに出す。
        self._source = self.BACKEND_NONE
        self._frame_source = None
        self._last_check = 0.0
        self._failures = OcrFailureLog("OCR capture", lambda: errorLogging(), lambda message: printLog(message))

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

    def _sharedBackend(self, backend: str) -> str:
        """Linux: the backend to read now, given the one chosen without the shared window."""
        if self._shared.isActive():
            self._shared_state = "active"
            self._backend = self.BACKEND_PORTAL
            return self._backend
        if self._shared_state == "active":
            # It was being read and is gone: the window was closed, or sharing was stopped.
            self._shared_state = "ended"
            printLog("OCR capture: the shared window is gone")
        if backend == self.BACKEND_PORTAL:
            self._backend = self._window_backend if self._window.isAvailable() else self.BACKEND_NONE
            return self._backend
        return backend

    def _noteSource(self, backend: str) -> None:
        self._frame_source = "vr" if backend == self.BACKEND_OPENVR else "window"
        if self._source != backend:
            printLog(f"OCR capture backend -> {backend}")
            self._source = backend

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def sharedWindow(self) -> Optional[str]:
        """"active" while a window the user shares is read, "ended" when it is gone and nothing replaced it."""
        return self._shared_state

    @property
    def source(self) -> Optional[str]:
        """Surface of the latest get() result, or None when no frame was read."""
        return self._frame_source

    def get(self) -> Optional[np.ndarray]:
        self._failures.report(time.monotonic())
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
                        self._frame_source = None
                        return None
                    self._noteSource(self.BACKEND_OPENVR)
                    self._failures.success()
                    return frame
                # VRChat is not the SteamVR scene (desktop mode, SteamVR Home)
                # or the VR read failed: use the desktop window until the
                # next recheck instead of reading nothing.
                self._backend = self._window_backend if self._window.isAvailable() else self.BACKEND_NONE
                backend = self._backend
            if self._shared is not None:
                backend = self._sharedBackend(backend)
            if backend == self.BACKEND_PORTAL:
                frame = self._shared.capture()
                # No picture yet, or a minimized window's last black one.
                if isFrameBlank(frame):
                    self._frame_source = None
                    return None
                self._noteSource(self.BACKEND_PORTAL)
                self._failures.success()
                return frame
            if backend == self._window_backend:
                frame = self._window.capture()
                # A minimized or occluded window keeps returning a stale black
                # buffer, so the stricter thresholds earn their keep here.
                if isFrameBlank(frame):
                    if self._shared_state == "ended":
                        raise SharedWindowEnded("The shared window is gone")
                    self._frame_source = None
                    return None
                # A window found by name is readable: the lost one is no longer missed.
                self._shared_state = None
                self._noteSource(self._window_backend)
                self._failures.success()
                return frame
            if self._shared_state == "ended":
                # Say so instead of waiting for a picture that cannot come.
                raise SharedWindowEnded("The shared window is gone")
        except Exception as exc:
            self._failures.failure(exc)
        self._frame_source = None
        return None

    def close(self) -> None:
        self._failures.reset()
        try:
            self._window.close()
        except Exception:
            pass
        if self._shared is not None:
            self._shared.close()
        self._shared_state = None
        if self._openvr is not None:
            try:
                self._openvr.close()
            except Exception:
                pass
            self._openvr = None
        self._backend = self.BACKEND_NONE
        self._source = self.BACKEND_NONE
        self._frame_source = None
