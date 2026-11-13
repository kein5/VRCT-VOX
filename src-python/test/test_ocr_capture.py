"""OCRのキャプチャ経路選択のテスト。

VRの読み出しで何も取れない (VRChatがSteamVRのシーンでない、読み出し失敗) とき、
以前は何も読めないまま待ち続けていた。デスクトップ画面の取得へ切り替えることを見る。
"""

import ctypes
import importlib.util
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from models.ocr import ocr_capture_hwnd
from models.ocr.ocr_capture import OcrCapture
from models.ocr.ocr_capture_openvr import OpenVRMirrorCapture


def _frame() -> np.ndarray:
    return np.random.default_rng(0).integers(0, 255, (8, 8, 3), dtype=np.uint8)


class TestFallbackToDesktopWindow(unittest.TestCase):
    def setUp(self):
        # This suite exercises the Windows mirror path using fake backends.
        platform = patch("models.ocr.ocr_capture.sys.platform", "win32")
        platform.start()
        self.addCleanup(platform.stop)

    def _make(self, vr_frame):
        capture = OcrCapture()
        capture._openvr = MagicMock()
        capture._openvr.isAvailable.return_value = True
        capture._openvr.capture.return_value = vr_frame
        capture._window = MagicMock()
        capture._window.isAvailable.return_value = True
        capture._window.capture.return_value = _frame()
        return capture

    def test_vr_frame_is_used_when_available(self) -> None:
        vr = _frame()
        capture = self._make(vr)
        with patch("models.ocr.ocr_capture._isSteamvrRunning", return_value=True):
            self.assertIs(capture.get(), vr)
        capture._window.capture.assert_not_called()

    def test_falls_back_to_the_window_when_vr_gives_nothing(self) -> None:
        capture = self._make(None)
        with patch("models.ocr.ocr_capture._isSteamvrRunning", return_value=True):
            frame = capture.get()
            self.assertIsNotNone(frame)
            self.assertEqual(capture.backend, capture._window_backend)
            # 次の再判定までは VR を試し直さない。
            capture.get()
        capture._openvr.capture.assert_called_once()

    def test_only_a_truly_uniform_vr_frame_is_dropped(self) -> None:
        dark = np.zeros((1455, 2575, 3), np.uint8)
        with patch("models.ocr.ocr_capture._isSteamvrRunning", return_value=True):
            self.assertIsNone(self._make(dark).get())
            dark[700, 1001] = 1  # a night world: one pixel off a uniform frame is still a scene
            self.assertIs(self._make(dark).get(), dark)


class TestVrchatSceneCheck(unittest.TestCase):
    """VRChat 以外 (SteamVR Home 等) のシーンは読まない。判定は収集ツールで実機確認済みの方法。"""

    def _make(self, renderer: int, focus: int):
        capture = OpenVRMirrorCapture()
        capture._mirror = MagicMock()
        capture._session_held = True
        capture._compositor = MagicMock()
        capture._compositor.getLastFrameRenderer.return_value = renderer
        capture._compositor.getCurrentSceneFocusProcess.return_value = focus
        return capture

    def _name(self, name: str):
        process = MagicMock()
        process.return_value.name.return_value = name
        return patch("models.ocr.ocr_capture_openvr.Process", process)

    def test_other_scene_app_is_not_read_and_session_is_kept(self) -> None:
        capture = self._make(renderer=100, focus=100)
        with self._name("vrserver.exe"), \
                patch("models.ocr.ocr_capture_openvr.openvr_session.release") as release:
            self.assertIsNone(capture.capture())
        # 異常ではないので、次に VRChat へ戻ったときのためにセッションは保持する。
        release.assert_not_called()
        self.assertIsNotNone(capture._mirror)
        capture._mirror.read.assert_not_called()

    def test_vrchat_frame_is_returned_as_bgr(self) -> None:
        # D3D11Mirror は収集ツール向けに RGB で返す。OCR は HWND 経路と同じ BGR。
        capture = self._make(renderer=100, focus=100)
        rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        rgb[..., 0] = 10
        rgb[..., 2] = 30
        capture._mirror.read.return_value = rgb
        with self._name("VRChat.exe"):
            frame = capture.capture()
        self.assertEqual(tuple(frame[0, 0]), (30, 0, 10))

    def test_repeated_failures_log_once_until_a_frame_is_read(self) -> None:
        # SteamVR 再起動中などは5秒ごとに再試行する。error.log を毎回汚さない。
        capture = OpenVRMirrorCapture()
        with patch.object(OpenVRMirrorCapture, "isAvailable", return_value=True),                 patch("models.ocr.ocr_capture_openvr.openvr_session.acquire", side_effect=RuntimeError("no vr")),                 patch("models.ocr.ocr_capture_openvr.errorLogging") as logging:
            for _ in range(3):
                self.assertIsNone(capture.capture())
        logging.assert_called_once()

    def test_vrchat_scene_is_detected(self) -> None:
        with self._name("VRChat.exe"):
            self.assertTrue(self._make(renderer=100, focus=100)._isVrchatScene())
            # 描画プロセスとフォーカスが食い違う (切り替え途中) ときは読まない。
            self.assertFalse(self._make(renderer=100, focus=200)._isVrchatScene())
            self.assertFalse(self._make(renderer=0, focus=0)._isVrchatScene())


class FrameBlankTest(unittest.TestCase):
    def test_black_and_uniform_frames_are_blank_but_a_dark_scene_with_text_is_not(self):
        from models.ocr.ocr_capture_hwnd import isFrameBlank

        black = np.zeros((1455, 2575, 3), np.uint8)
        self.assertTrue(isFrameBlank(black))
        self.assertTrue(isFrameBlank(black + 2))
        scene = black.copy()
        scene[500:800, 900:1700] = 255  # a chat bubble in a night window (the whole-frame mean stays above 3)
        self.assertFalse(isFrameBlank(scene))
        self.assertFalse(isFrameBlank(np.random.default_rng(0).integers(0, 256, (1455, 2575, 3), dtype=np.uint8)))


@pytest.mark.parametrize("operation,result", [
    ("GetWindowDC", 0), ("CreateCompatibleDC", 0), ("CreateCompatibleBitmap", 0),
    ("PrintWindow", 0), ("GetDIBits", 0), ("GetDIBits", 4),
])
def test_native_hwnd_failures_raise_and_release_allocated_handles(monkeypatch, operation, result):
    # Load the Windows branch with fake DLLs; no native window or DLL is opened.
    user32, gdi32 = MagicMock(), MagicMock()
    user32.GetWindowDC.return_value = 10
    user32.PrintWindow.return_value = 1
    gdi32.CreateCompatibleDC.return_value = 20
    gdi32.CreateCompatibleBitmap.return_value = 30
    gdi32.SelectObject.return_value = 40
    gdi32.GetDIBits.return_value = 8
    owner = user32 if operation in ("GetWindowDC", "PrintWindow") else gdi32
    getattr(owner, operation).return_value = result
    spec = importlib.util.spec_from_file_location("models.ocr._test_hwnd_native", ocr_capture_hwnd.__file__)
    native = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as windows:
        windows.setattr(ocr_capture_hwnd.sys, "platform", "win32")
        windows.setattr(ctypes, "WinDLL", lambda name, **kwargs: user32 if name == "user32" else gdi32,
                        raising=False)
        spec.loader.exec_module(native)
    with pytest.raises(OSError, match=operation):
        native._print_window(42, 8, 8)
    if operation == "GetWindowDC":
        user32.ReleaseDC.assert_not_called()
    else:
        user32.ReleaseDC.assert_called_once_with(42, 10)
    if operation not in ("GetWindowDC", "CreateCompatibleDC"):
        gdi32.DeleteDC.assert_called_once_with(20)
    if operation in ("PrintWindow", "GetDIBits"):
        gdi32.SelectObject.assert_any_call(20, 40)
        gdi32.DeleteObject.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
