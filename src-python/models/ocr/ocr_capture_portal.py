"""A window the user shares through the desktop's ScreenCast portal (Linux).

X11 can read VRChat's window by its name (ocr_capture_x11.py). A native
Wayland window (VRChat inside gamescope, or with Wine's Wayland driver) is
out of its reach: on Wayland only the desktop hands out a window's picture,
and only after the user picked that window in the desktop's own dialog.

The asking is done by the Tauri process, on the user's request in the
chat-reading settings (src-tauri/src/portal_screencast.rs). It starts a small
helper (native/screen-capture) that copies the newest frame of the stream into
`<directory>/screen-frame`; `<directory>` is the private one Tauri announces in
VRCT_VR_PANEL_DIR. This module only reads that file. It never starts a capture.

File layout (little-endian): a 64-byte header, then the pixels.
    0  "VRCTSCR1"
    8  sequence, odd while the pixels are being replaced
    16 instance: 0 once the stream is gone; the upper half is the helper's process id
    24 width, 28 height, 32 bytes per row, 36 pixel layout (0 BGRx, 1 BGRA, 2 RGBx, 3 RGBA)
    40 time of the frame (CLOCK_MONOTONIC, nanoseconds)
Rows are `bytes per row` apart; the last one holds only width * 4 bytes.

A window that does not change sends no new frames, so an old frame is not a
dead stream. The stream is over when the file is gone, when its instance is 0,
or when the helper that wrote it no longer exists.
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

DIRECTORY_ENV = "VRCT_VR_PANEL_DIR"
FRAME_NAME = "screen-frame"

_MAGIC = b"VRCTSCR1"
_HEADER = struct.Struct("<8sQQIIIIQ")
_HEADER_SIZE = 64
_MAX_SIDE = 16384
_READ_TRIES = 4
_RGB_LAYOUTS = (2, 3)
_LAYOUTS = (0, 1, 2, 3)


class SharedWindowError(RuntimeError):
    """The frame file holds something that cannot be read as a picture."""


def framePath() -> Optional[Path]:
    directory = os.environ.get(DIRECTORY_ENV)
    return Path(directory) / FRAME_NAME if directory else None


def _writerAlive(instance: int) -> bool:
    """A helper that was killed cannot mark its file as over; its process id tells."""
    return os.path.exists(f"/proc/{instance >> 32}")


def parseHeader(head: bytes) -> Optional[Tuple[int, int, int, int, int, int]]:
    """(sequence, instance, width, height, bytes per row, layout), or None when this is not a frame file."""
    if len(head) < _HEADER.size:
        return None
    magic, sequence, instance, width, height, stride, layout, _time = _HEADER.unpack_from(head)
    if magic != _MAGIC or width > _MAX_SIDE or height > _MAX_SIDE or stride > _MAX_SIDE * 8:
        return None
    if (width == 0) != (height == 0) or (width and stride < width * 4):
        return None
    return sequence, instance, width, height, stride, layout


def frameFromPixels(width: int, height: int, stride: int, layout: int, data: bytes) -> Optional[np.ndarray]:
    """Rows of 4-byte pixels, `stride` bytes apart -> BGR ndarray. Unknown layouts -> None."""
    if layout not in _LAYOUTS or width <= 0 or height <= 0 or stride < width * 4:
        return None
    if len(data) < stride * (height - 1) + width * 4:
        return None
    pixels = np.lib.stride_tricks.as_strided(
        np.frombuffer(data, dtype=np.uint8), shape=(height, width, 4), strides=(stride, 4, 1), writeable=False)
    # The fourth byte is padding or alpha; chat reading wants the colours only.
    return np.ascontiguousarray(pixels[:, :, 2::-1] if layout in _RGB_LAYOUTS else pixels[:, :, :3])


def _read(stream, offset: int, size: int) -> bytes:
    stream.seek(offset)
    parts, left = [], size
    while left > 0:
        part = stream.read(left)
        if not part:
            break
        parts.append(part)
        left -= len(part)
    return parts[0] if len(parts) == 1 else b"".join(parts)


class SharedWindowCapture:
    """Reads the newest frame of the shared window. The facade decides when to use it."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path
        self._cache: Optional[tuple] = None  # (instance, sequence, frame)

    def _file(self) -> Optional[Path]:
        return self._path if self._path is not None else framePath()

    def isActive(self) -> bool:
        """Is a window shared right now? Cheap: reads the 64-byte header only."""
        path = self._file()
        if path is None:
            return False
        try:
            with open(path, "rb", buffering=0) as stream:
                parsed = parseHeader(_read(stream, 0, _HEADER_SIZE))
        except OSError:
            return False
        return parsed is not None and parsed[1] != 0 and _writerAlive(parsed[1])

    def capture(self) -> Optional[np.ndarray]:
        """The newest frame as BGR, or None while the stream has not sent one (or is gone).

        An unchanged frame is returned again as the same array; callers must not write to it.
        """
        path = self._file()
        if path is None:
            return None
        instance = 0
        try:
            with open(path, "rb", buffering=0) as stream:
                for _ in range(_READ_TRIES):
                    head = _read(stream, 0, _HEADER_SIZE)
                    parsed = parseHeader(head)
                    if parsed is None or parsed[1] == 0:
                        return None
                    sequence, instance, width, height, stride, layout = parsed
                    if sequence % 2:
                        time.sleep(0.001)  # the pixels are being replaced
                        continue
                    if width == 0:
                        return None
                    if self._cache is not None and self._cache[:2] == (instance, sequence):
                        return self._cache[2]
                    size = stride * (height - 1) + width * 4
                    data = _read(stream, _HEADER_SIZE, size)
                    if len(data) != size or _read(stream, 0, 24) != head[:24]:
                        continue  # replaced while it was read
                    frame = frameFromPixels(width, height, stride, layout, data)
                    if frame is None:
                        raise SharedWindowError("Unsupported pixel layout in the shared window's frame")
                    self._cache = (instance, sequence, frame)
                    return frame
        except OSError:
            return None
        # The writer kept replacing the frame: the previous one of the same stream is still a true picture.
        return self._cache[2] if self._cache is not None and self._cache[0] == instance else None

    def close(self) -> None:
        self._cache = None
