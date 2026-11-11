"""Linux: 貼り付け先のウィンドウを前面に出し、Ctrl+V を送る (X11 / XWayland のウィンドウだけ)。

Proton で動く VRChat は XWayland のウィンドウなので、X11 の手順がそのまま使える。ウィンドウを探す
のはチャット読み取りと同じ処理 (ocr_capture_x11)。前面に出すのは、ウィンドウマネージャーへの
依頼 (_NET_ACTIVE_WINDOW)。キーは XTest で送る。XTest のキーは X11 のウィンドウにだけ届くので、
貼り付け先が実際に前面に出たことを確かめてから送る (そうでないと、何にも届かない)。
Wayland ネイティブのウィンドウには貼り付けられない。
"""
import ctypes
import ctypes.util
import os
import sys
import time
from typing import Optional

try:
    from models.ocr import ocr_capture_x11 as x11
except ImportError:  # 単体で読み込んだとき
    x11 = None  # type: ignore

_CLIENT_MESSAGE = 33
_SUBSTRUCTURE_MASK = (1 << 19) | (1 << 20)  # SubstructureNotify | SubstructureRedirect
_SOURCE_PAGER = 2  # 利用者の操作を代行する道具からの依頼。ウィンドウマネージャーはそのまま聞き入れる
_XK_CONTROL_L = 0xFFE3
_XK_V = 0x0076
_ACTIVATE_WAIT_SEC = 0.6


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _Event(ctypes.Union):
    # XEvent は long 24個分。小さい構造体を渡すと、Xlib が外まで読む
    _fields_ = [("message", _ClientMessage), ("pad", ctypes.c_long * 24)]


_xtst = None
_xtst_loaded = False


def _loadXtst():
    global _xtst, _xtst_loaded
    if _xtst_loaded:
        return _xtst
    _xtst_loaded = True
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
    except OSError:
        return None
    lib.XTestFakeKeyEvent.restype = ctypes.c_int
    lib.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    _xtst = lib
    return lib


class X11Paster(x11.X11WindowCapture if x11 is not None else object):
    """1回の貼り付けのための接続。使い終わったら close する。"""

    def isAvailable(self) -> bool:
        if x11 is None or not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
            return False
        return _loadXtst() is not None and super().isAvailable()

    def find(self, name: str) -> Optional[int]:
        """題名 (完全一致、次に部分一致)、次にクラス名・プロセス名で探す。Windows と同じ順。"""
        self.window_title = name
        try:
            return self.findWindow()
        except x11.X11CaptureError:
            return None

    def _active(self) -> int:
        windows = self._windows(x11._State.lib.XDefaultRootWindow(self._display), "_NET_ACTIVE_WINDOW")
        return windows[0] if windows else 0

    def focus(self, window: int) -> bool:
        """前面に出すよう頼み、実際に出たら True。"""
        lib = x11._load()
        if lib is None or self._open() is None:
            return False
        self._begin()
        if self._active() == window:
            return True
        lib.XSendEvent.restype = ctypes.c_int
        lib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
        event = _Event()
        event.message.type = _CLIENT_MESSAGE
        event.message.window = window
        event.message.message_type = self._atom("_NET_ACTIVE_WINDOW")
        event.message.format = 32
        event.message.data[0] = _SOURCE_PAGER
        root = lib.XDefaultRootWindow(self._display)
        lib.XSendEvent(self._display, root, 0, _SUBSTRUCTURE_MASK, ctypes.byref(event))
        deadline = time.monotonic() + _ACTIVATE_WAIT_SEC
        while True:
            if self._failed():
                return False
            if self._active() == window:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def paste(self) -> bool:
        """前面の X11 のウィンドウへ Ctrl+V を送る。"""
        lib, xtst = x11._load(), _loadXtst()
        if lib is None or xtst is None or self._open() is None:
            return False
        lib.XKeysymToKeycode.restype = ctypes.c_ubyte
        lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        control, letter = (lib.XKeysymToKeycode(self._display, key) for key in (_XK_CONTROL_L, _XK_V))
        if not control or not letter:
            return False
        self._begin()
        for keycode, press in ((control, 1), (letter, 1), (letter, 0), (control, 0)):
            xtst.XTestFakeKeyEvent(self._display, keycode, press, 0)
        return not self._failed()
