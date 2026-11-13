"""VRパネル用 (Linux): Tauri が画面に出さずに描いた VR画面を読み、ポインタの操作を送る。

Wayland では、ウィンドウを画面外に置くことも、ほかのウィンドウを撮ることもできない。そのため Tauri 側
(src-tauri/src/vr_panel_surface.rs) が VR画面を GtkOffscreenWindow に移し、描き直すたびに画素を
`<場所>/frame` へ書く。ポインタは `<場所>/input.sock` へ1行ずつ送ると、GDK のイベントとして VR画面に届く。
`<場所>` は Tauri が起動時に決め、環境変数 VRCT_VR_PANEL_DIR でバックエンドへ渡す。

関数の名前と戻り値は window_capture (Windows) と同じ。ウィンドウの番号 (hwnd) の代わりに、VR画面を
作るたびに変わる番号 (instance) を使う。
"""
import os
import socket
import struct
import time
from pathlib import Path
from threading import Lock
from typing import Optional

import numpy as np

DIRECTORY_ENV = "VRCT_VR_PANEL_DIR"
VR_PANEL_TITLE = "VRCT-VOX VR Panel"

_MAGIC = b"VRCTVRP1"
# 先頭64バイト: 目印, 通し番号 (書き換え中は奇数), VR画面の番号 (0 は無い), 幅, 高さ, 1行のバイト数
_HEADER = struct.Struct("<8sQQIII")
_HEADER_SIZE = 64
_MAX_SIDE = 8192
_READ_TRIES = 4
# Windows のホイールは120で1目盛り (WebView2 では約100px)。GDK は1.0で約50px、下向きが正
_WHEEL_UNITS_PER_GDK_DELTA = -60.0

_lock = Lock()
_cache: Optional[tuple] = None  # (instance, sequence, raw, (幅, 高さ))
_expected: dict = {}  # instance -> resizeClient で頼んだ大きさ
_sender: Optional[socket.socket] = None


def directory() -> Optional[Path]:
    value = os.environ.get(DIRECTORY_ENV)
    return Path(value) if value else None


def available() -> bool:
    """Tauri が VR画面を渡す場所を用意したか (バックエンドだけを起動したときは無い)。"""
    path = directory()
    return path is not None and path.is_dir()


def _parse(head: bytes) -> Optional[tuple]:
    if len(head) < _HEADER.size:
        return None
    magic, sequence, instance, width, height, stride = _HEADER.unpack_from(head)
    if magic != _MAGIC or width > _MAX_SIDE or height > _MAX_SIDE or (width and stride < width * 4) or stride > _MAX_SIDE * 4:
        return None
    return sequence, instance, width, height, stride


def _header() -> Optional[tuple]:
    path = directory()
    if path is None:
        return None
    try:
        fd = os.open(path / "frame", os.O_RDONLY)
    except OSError:
        return None
    try:
        return _parse(os.pread(fd, _HEADER_SIZE, 0))
    except OSError:
        return None
    finally:
        os.close(fd)


def _latest(instance: int) -> Optional[tuple]:
    """VR画面 instance の最新の画像 (BGRA のバイト列, (幅, 高さ))。まだ1枚も無い、または別の VR画面なら None。"""
    global _cache
    path = directory()
    if path is None:
        return None
    try:
        fd = os.open(path / "frame", os.O_RDONLY)
    except OSError:
        return None
    try:
        with _lock:
            for _ in range(_READ_TRIES):
                head = os.pread(fd, _HEADER_SIZE, 0)
                parsed = _parse(head)
                if parsed is None or parsed[1] != instance:
                    return None
                sequence, _, width, height, stride = parsed
                if sequence % 2:
                    time.sleep(0.001)  # 書き換えの途中
                    continue
                if width == 0 or height == 0:
                    return None
                if _cache is not None and _cache[:2] == (instance, sequence):
                    return _cache[2:]
                raw = os.pread(fd, stride * height, _HEADER_SIZE)
                if len(raw) != stride * height or os.pread(fd, 16, 0) != head[:16]:
                    continue  # 読んでいる間に書き換わった
                if stride != width * 4:
                    raw = np.frombuffer(raw, np.uint8).reshape(height, stride)[:, :width * 4].tobytes()
                _cache = (instance, sequence, raw, (width, height))
                return _cache[2:]
            # 書き換えが続いた: 同じ VR画面の前の画像があれば、それを使う
            return _cache[2:] if _cache is not None and _cache[0] == instance else None
    except OSError:
        return None
    finally:
        os.close(fd)


def findWindow(title: str = VR_PANEL_TITLE) -> Optional[int]:
    parsed = _header()
    return (parsed[1] or None) if parsed is not None else None


def isWindow(hwnd: int) -> bool:
    parsed = _header()
    return parsed is not None and parsed[1] == hwnd and hwnd != 0


def captureWindowRaw(hwnd: int) -> Optional[tuple]:
    """最新の画像を (BGRA のバイト列, (幅, 高さ), 切り出し範囲) で返す。まだ無ければ None。"""
    latest = _latest(hwnd)
    if latest is None:
        return None
    raw, size = latest
    return raw, size, (0, 0, *size)


class WindowStream:
    """届いている最新の1枚を返す。Linux では画像は常に Tauri から届くので、続けて撮る仕組みは持たない。"""

    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        # 最新の画像が、頼んだ大きさとまだ違う (take が None を返した理由)
        self.stale = False

    @property
    def closed(self) -> bool:
        return not isWindow(self.hwnd)

    def take(self) -> Optional[tuple]:
        self.stale = False
        capture = captureWindowRaw(self.hwnd)
        if capture is None:
            return None
        expected = _expected.get(self.hwnd)
        if expected is not None and capture[1] != expected:
            self.stale = True
            return None
        return capture

    def close(self) -> None:
        pass


def _send(text: str) -> None:
    global _sender
    path = directory()
    if path is None:
        return
    try:
        if _sender is None:
            _sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            _sender.setblocking(False)
        _sender.sendto(text.encode("ascii"), str(path / "input.sock"))
    except OSError:
        pass  # VR画面がまだ無い・消えた。次の撮影で気づく


def resizeClient(hwnd: int, width: int, height: int) -> tuple:
    """VR画面を width x height にするよう頼む。戻り値は、画像がこの大きさになれば変わり終えている大きさ。"""
    size = (int(width), int(height))
    # 古い VR画面の分は要らない
    for old in [key for key in _expected if key != hwnd]:
        del _expected[old]
    _expected[hwnd] = size
    _send(f"resize {size[0]} {size[1]}")
    return size


def bgraFromCapture(capture: tuple) -> np.ndarray:
    """captureWindowRaw の結果から、画素 (高さ, 幅, BGRA) を切り出す (書き換えてよい複製)。"""
    raw, (width, height), (x0, y0, x1, y1) = capture
    return np.frombuffer(raw, np.uint8).reshape(height, width, 4)[y0:y1, x0:x1].copy()


def mouseMove(hwnd: int, x: int, y: int, pressed: bool = False) -> None:
    _send(f"move {int(x)} {int(y)} {1 if pressed else 0}")


def mouseDown(hwnd: int, x: int, y: int) -> None:
    _send(f"down {int(x)} {int(y)}")


def mouseUp(hwnd: int, x: int, y: int) -> None:
    _send(f"up {int(x)} {int(y)}")


def mouseWheel(hwnd: int, x: int, y: int, delta: int) -> None:
    _send(f"wheel {int(x)} {int(y)} {delta / _WHEEL_UNITS_PER_GDK_DELTA:.4f}")
