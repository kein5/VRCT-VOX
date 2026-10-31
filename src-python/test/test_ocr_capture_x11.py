"""X11/XWayland window capture without an X server: pixel layouts, window choice, probing.

Never opens the user's display: X calls are replaced by a fake window table.
"""

import unittest
from unittest.mock import patch

import numpy as np

from models.ocr import ocr_capture, ocr_capture_x11
from models.ocr.ocr_capture import CAPTURE_OK, CAPTURE_UNAVAILABLE, CAPTURE_WINDOW_NOT_FOUND, probeCapture
from models.ocr.ocr_capture_x11 import X11WindowCapture, frameFromXImage


class TestPixelLayouts(unittest.TestCase):
    def _bytes(self, pixels, pad=0):
        h, w, _ = pixels.shape
        rows = np.zeros((h, w * 4 + pad), np.uint8)
        rows[:, :w * 4] = pixels.reshape(h, w * 4)
        return rows.tobytes(), w * 4 + pad

    def test_bgrx_little_endian_is_the_common_case(self) -> None:
        bgrx = np.array([[[10, 20, 30, 0], [40, 50, 60, 0]]], np.uint8)
        data, stride = self._bytes(bgrx, pad=8)
        frame = frameFromXImage(2, 1, stride, 32, 0xFF0000, 0xFF, 0, data)
        np.testing.assert_array_equal(frame, [[[10, 20, 30], [40, 50, 60]]])
        self.assertTrue(frame.flags["C_CONTIGUOUS"])

    def test_rgbx_is_swapped_to_bgr(self) -> None:
        rgbx = np.array([[[30, 20, 10, 0]]], np.uint8)
        data, stride = self._bytes(rgbx)
        np.testing.assert_array_equal(frameFromXImage(1, 1, stride, 32, 0xFF, 0xFF0000, 0, data), [[[10, 20, 30]]])

    def test_big_endian_xrgb(self) -> None:
        xrgb = np.array([[[0, 30, 20, 10]]], np.uint8)
        data, stride = self._bytes(xrgb)
        np.testing.assert_array_equal(frameFromXImage(1, 1, stride, 32, 0xFF0000, 0xFF, 1, data), [[[10, 20, 30]]])

    def test_unsupported_layouts_give_nothing(self) -> None:
        self.assertIsNone(frameFromXImage(1, 1, 2, 16, 0xF800, 0x1F, 0, b"\0\0"))
        self.assertIsNone(frameFromXImage(2, 1, 4, 32, 0xFF0000, 0xFF, 0, b"\0" * 4))  # stride too short
        self.assertIsNone(frameFromXImage(1, 1, 4, 32, 0xFF0000, 0xFF, 0, b"\0"))      # truncated
        self.assertIsNone(frameFromXImage(1, 1, 4, 32, 0x7C00, 0x1F, 0, b"\0" * 4))


class _FakeX:
    """Window table standing in for the X server."""

    def __init__(self, windows):
        self.windows = windows  # id -> dict(title, classes, pid, viewable)
        self.grabs = []

    def install(self, test, capture):
        for name, fn in (
            ("_open", lambda: "display"), ("_begin", lambda: None), ("_failed", lambda: False),
            ("_candidates", lambda: list(self.windows)),
            ("_title", lambda w: self.windows[w].get("title", "")),
            ("_classes", lambda w: list(self.windows[w].get("classes", []))),
            ("_pid", lambda w: self.windows[w].get("pid", 0)),
            ("_viewable", lambda w: object() if self.windows.get(w, {}).get("viewable", True) else None),
            ("_grab", self._grab),
        ):
            p = patch.object(capture, name, side_effect=fn)
            p.start()
            test.addCleanup(p.stop)
        capture._display = "display"

    def _grab(self, window):
        self.grabs.append(window)
        info = self.windows.get(window)
        if info is None or not info.get("viewable", True):
            return None
        return np.full((4, 4, 3), window % 255, np.uint8)


class TestFindWindow(unittest.TestCase):
    def _capture(self, windows, title="VRChat"):
        capture = X11WindowCapture(window_title=title)
        fake = _FakeX(windows)
        fake.install(self, capture)
        return capture, fake

    def test_exact_title_beats_substring_and_class(self) -> None:
        capture, _ = self._capture({
            1: {"title": "VRChat - Discord"},
            2: {"title": "", "classes": ["steam_app_438100", "vrchat.exe"]},
            3: {"title": "VRChat"},
        })
        self.assertEqual(capture.findWindow(), 3)

    def test_substring_then_proton_class_or_process(self) -> None:
        capture, _ = self._capture({1: {"title": "Firefox"}, 2: {"title": "my vrchat window"}})
        self.assertEqual(capture.findWindow(), 2)
        capture, _ = self._capture({1: {"title": "Firefox"}, 2: {"title": "", "classes": ["steam_app_438100", "vrchat.exe"]}})
        self.assertEqual(capture.findWindow(), 2)
        with patch.object(ocr_capture_x11, "_processName", return_value="vrchat.exe"):
            capture, _ = self._capture({1: {"title": "Unity", "pid": 4242}}, title="VRChat.exe")
            self.assertEqual(capture.findWindow(), 1)

    def test_unmapped_windows_are_skipped(self) -> None:
        capture, _ = self._capture({1: {"title": "VRChat", "viewable": False}})
        self.assertIsNone(capture.findWindow())

    def test_capture_follows_the_window_and_looks_again_when_it_goes(self) -> None:
        windows = {7: {"title": "VRChat"}}
        capture, fake = self._capture(windows)
        self.assertEqual(int(capture.capture()[0, 0, 0]), 7)
        self.assertEqual(capture._window, 7)
        windows[7]["viewable"] = False
        self.assertIsNone(capture.capture())
        self.assertIsNone(capture._window)
        windows[9] = {"title": "VRChat"}
        del windows[7]
        self.assertEqual(int(capture.capture()[0, 0, 0]), 9)

    def test_x_errors_drop_the_frame(self) -> None:
        capture, _ = self._capture({7: {"title": "VRChat"}})
        with patch.object(capture, "_failed", return_value=True):
            self.assertIsNone(capture.capture())
        self.assertIsNone(capture._window)


class TestAvailability(unittest.TestCase):
    def test_no_display_means_unavailable(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch.object(ocr_capture_x11.sys, "platform", "linux"):
            self.assertFalse(X11WindowCapture().isAvailable())

    def test_windows_never_uses_x11(self) -> None:
        with patch.object(ocr_capture_x11.sys, "platform", "win32"):
            self.assertFalse(X11WindowCapture(display_name=":0").isAvailable())


class TestProbe(unittest.TestCase):
    def _probe(self, available, window):
        class Fake:
            closed = False

            def __init__(self, window_title):
                self.title = window_title

            def isAvailable(self):
                return available

            def findWindow(self):
                return window

            def close(self):
                Fake.closed = True

        with patch.object(ocr_capture.sys, "platform", "linux"), patch.object(ocr_capture, "X11WindowCapture", Fake):
            result = probeCapture("VRChat")
        self.assertTrue(Fake.closed)
        return result

    def test_linux_results(self) -> None:
        self.assertEqual(self._probe(False, None), CAPTURE_UNAVAILABLE)
        self.assertEqual(self._probe(True, None), CAPTURE_WINDOW_NOT_FOUND)
        self.assertEqual(self._probe(True, 5), CAPTURE_OK)

    def test_facade_uses_x11_on_linux(self) -> None:
        with patch.object(ocr_capture.sys, "platform", "linux"):
            capture = ocr_capture.OcrCapture(window_title="VRChat")
        self.assertEqual(capture._window_backend, ocr_capture.OcrCapture.BACKEND_X11)
        self.assertIsInstance(capture._window, X11WindowCapture)

    def test_facade_reads_the_x11_window_frame(self) -> None:
        frame = np.random.default_rng(0).integers(0, 255, (32, 32, 3), dtype=np.uint8)
        with patch.object(ocr_capture.sys, "platform", "linux"):
            capture = ocr_capture.OcrCapture(window_title="VRChat")
        with patch.object(capture._window, "isAvailable", return_value=True), \
                patch.object(capture._window, "capture", return_value=frame), \
                patch.object(ocr_capture, "_isSteamvrRunning", return_value=False):
            self.assertIs(capture.get(), frame)
        self.assertEqual(capture.backend, ocr_capture.OcrCapture.BACKEND_X11)


if __name__ == "__main__":
    unittest.main()
