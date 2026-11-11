"""A window shared through the ScreenCast portal: the frame file, the facade's choice, and how a lost window is reported.

Nothing here talks to a portal or to PipeWire: the frame file is written by the test, and the
platform is faked so the same cases run on Linux and Windows.
"""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from config import config
from controller import Controller
from errors import ErrorCode
from models.ocr import ocr_capture, ocr_capture_portal, ocr_pipeline
from models.ocr.ocr_capture import CAPTURE_OK, CAPTURE_UNAVAILABLE, OcrCapture, SharedWindowEnded, probeCapture
from models.ocr.ocr_capture_portal import SharedWindowCapture, SharedWindowError, frameFromPixels, parseHeader

INSTANCE = (4242 << 32) | 1
_writerAlive = ocr_capture_portal._writerAlive  # the real one; the cases below replace it
BGRX, BGRA, RGBX, RGBA = 0, 1, 2, 3


def header(sequence=2, instance=INSTANCE, width=0, height=0, stride=0, layout=BGRX, magic=b"VRCTSCR1"):
    return struct.pack("<8sQQIIIIQ", magic, sequence, instance, width, height, stride, layout, 123).ljust(64, b"\0")


def picture(width=6, height=5, seed=0):
    """A BGR picture with enough detail not to count as a blank frame."""
    return np.random.default_rng(seed).integers(0, 255, (height, width, 3), dtype=np.uint8)


def pixels(bgr, layout=BGRX, pad=0):
    """The bytes the helper writes for `bgr`: rows `width * 4 + pad` apart, the last one without padding."""
    height, width, _ = bgr.shape
    rows = np.full((height, width * 4 + pad), 0xEE, np.uint8)
    four = np.full((height, width, 4), 0x7F, np.uint8)
    four[:, :, :3] = bgr[:, :, ::-1] if layout in (RGBX, RGBA) else bgr
    rows[:, :width * 4] = four.reshape(height, width * 4)
    data = rows.tobytes()
    return data[:len(data) - pad] if pad else data


def write(path, bgr, layout=BGRX, pad=0, sequence=2, instance=INSTANCE):
    height, width, _ = bgr.shape
    path.write_bytes(header(sequence, instance, width, height, width * 4 + pad, layout) + pixels(bgr, layout, pad))


class _Files(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "screen-frame"
        # The helper is not running in these tests; its process id counts as alive unless a case says otherwise.
        self.alive = self._patch(ocr_capture_portal, "_writerAlive", return_value=True)

    def _patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result


class TestFrameFile(_Files):
    def test_every_layout_becomes_bgr(self) -> None:
        bgr = picture()
        for layout in (BGRX, BGRA, RGBX, RGBA):
            write(self.path, bgr, layout)
            frame = SharedWindowCapture(self.path).capture()
            np.testing.assert_array_equal(frame, bgr, err_msg=str(layout))
            self.assertTrue(frame.flags["C_CONTIGUOUS"])

    def test_row_padding_is_skipped_and_the_last_row_may_be_short(self) -> None:
        bgr = picture(width=7, height=4)
        write(self.path, bgr, pad=12)
        self.assertEqual(self.path.stat().st_size, 64 + 3 * (7 * 4 + 12) + 7 * 4)
        np.testing.assert_array_equal(SharedWindowCapture(self.path).capture(), bgr)

    def test_an_unchanged_frame_is_not_read_again(self) -> None:
        write(self.path, picture())
        capture = SharedWindowCapture(self.path)
        first = capture.capture()
        self.assertIs(capture.capture(), first)
        newer = picture(seed=1)
        write(self.path, newer, sequence=4)
        np.testing.assert_array_equal(capture.capture(), newer)

    def test_a_frame_being_replaced_is_never_returned_half_written(self) -> None:
        bgr = picture()
        write(self.path, bgr)
        capture = SharedWindowCapture(self.path)
        np.testing.assert_array_equal(capture.capture(), bgr)
        # The writer is in the middle of the next frame: keep the last whole one.
        write(self.path, picture(seed=2), sequence=3)
        with patch.object(ocr_capture_portal.time, "sleep"):
            np.testing.assert_array_equal(capture.capture(), bgr)
            self.assertIsNone(SharedWindowCapture(self.path).capture())

    def test_no_picture_before_the_first_frame(self) -> None:
        self.path.write_bytes(header(sequence=0))
        capture = SharedWindowCapture(self.path)
        self.assertTrue(capture.isActive())
        self.assertIsNone(capture.capture())

    def test_the_stream_is_over_when_the_file_says_so_or_is_gone(self) -> None:
        capture = SharedWindowCapture(self.path)
        self.assertFalse(capture.isActive())
        self.assertIsNone(capture.capture())
        write(self.path, picture())
        self.assertTrue(capture.isActive())
        write(self.path, picture(), instance=0)
        self.assertFalse(capture.isActive())
        self.assertIsNone(capture.capture())

    def test_a_file_left_by_a_killed_helper_is_not_a_stream(self) -> None:
        write(self.path, picture())
        self.alive.return_value = False
        self.assertFalse(SharedWindowCapture(self.path).isActive())
        self.alive.assert_called_with(INSTANCE)

    def test_the_helpers_process_id_is_the_upper_half_of_the_instance(self) -> None:
        with patch.object(ocr_capture_portal.os.path, "exists", return_value=True) as exists:
            self.assertTrue(_writerAlive(INSTANCE))
        exists.assert_called_once_with("/proc/4242")

    def test_other_files_are_not_frames(self) -> None:
        for content in (b"", b"VRCTSCR1", header(magic=b"VRCTVRP1"), header(width=20000, height=10, stride=80000),
                        header(width=10, height=10, stride=8), header(width=10, height=0, stride=40)):
            self.path.write_bytes(content)
            capture = SharedWindowCapture(self.path)
            self.assertFalse(capture.isActive(), content[:40])
            self.assertIsNone(capture.capture(), content[:40])
        self.assertIsNone(parseHeader(b"short"))

    def test_an_unknown_pixel_layout_is_an_error_not_a_wrong_picture(self) -> None:
        write(self.path, picture(), layout=9)
        with self.assertRaises(SharedWindowError):
            SharedWindowCapture(self.path).capture()
        self.assertIsNone(frameFromPixels(2, 2, 8, 9, b"\0" * 16))
        self.assertIsNone(frameFromPixels(2, 2, 8, BGRX, b"\0" * 15))

    def test_a_truncated_file_gives_nothing(self) -> None:
        bgr = picture()
        write(self.path, bgr)
        self.path.write_bytes(self.path.read_bytes()[:-1])
        self.assertIsNone(SharedWindowCapture(self.path).capture())

    def test_the_file_is_found_through_the_directory_tauri_announces(self) -> None:
        write(self.path, picture())
        with patch.dict("os.environ", {ocr_capture_portal.DIRECTORY_ENV: str(self.path.parent)}):
            self.assertTrue(SharedWindowCapture().isActive())
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(SharedWindowCapture().isActive())
            self.assertIsNone(SharedWindowCapture().capture())


class _Facade(_Files):
    """OcrCapture on a pretend Linux, with a fake X11 window and the test's frame file."""

    def setUp(self):
        super().setUp()
        self._patch(ocr_capture.sys, "platform", new="linux")
        self._patch(ocr_capture, "_isSteamvrRunning", return_value=False)
        self._patch(ocr_capture, "errorLogging")
        self.logs = self._patch(ocr_capture, "printLog")
        environment = patch.dict("os.environ", {ocr_capture_portal.DIRECTORY_ENV: str(self.path.parent)})
        environment.start()
        self.addCleanup(environment.stop)
        self.x11_frame = picture(seed=7)
        self.capture = OcrCapture(window_title="VRChat")
        self.x11 = Mock()
        self.x11.isAvailable.return_value = True
        self.x11.capture.return_value = self.x11_frame
        self.capture._window = self.x11


class TestFacade(_Facade):
    def test_x11_stays_the_default_and_is_not_disturbed(self) -> None:
        self.assertIs(self.capture.get(), self.x11_frame)
        self.assertEqual(self.capture.backend, OcrCapture.BACKEND_X11)
        self.assertEqual(self.capture.source, "window")
        self.assertIsNone(self.capture.sharedWindow)

    def test_a_shared_window_is_read_instead_of_the_one_found_by_name(self) -> None:
        shared = picture(seed=3)
        write(self.path, shared)
        np.testing.assert_array_equal(self.capture.get(), shared)
        self.assertEqual(self.capture.backend, OcrCapture.BACKEND_PORTAL)
        # Still the desktop window as far as reading areas and the status are concerned.
        self.assertEqual(self.capture.source, "window")
        self.assertEqual(self.capture.sharedWindow, "active")
        self.x11.capture.assert_not_called()

    def test_sharing_started_later_takes_over_at_once(self) -> None:
        self.assertIs(self.capture.get(), self.x11_frame)
        shared = picture(seed=3)
        write(self.path, shared)
        np.testing.assert_array_equal(self.capture.get(), shared)
        self.assertEqual(self.capture.backend, OcrCapture.BACKEND_PORTAL)

    def test_a_shared_window_works_without_any_x11_display(self) -> None:
        self.x11.isAvailable.return_value = False
        self.assertIsNone(self.capture.get())
        self.assertFalse(self.capture._failures.active)
        shared = picture(seed=3)
        write(self.path, shared)
        np.testing.assert_array_equal(self.capture.get(), shared)

    def test_no_frame_yet_is_waiting_not_a_failure(self) -> None:
        self.path.write_bytes(header(sequence=0))
        self.assertIsNone(self.capture.get())
        self.assertIsNone(self.capture.source)
        self.assertEqual(self.capture.sharedWindow, "active")
        self.assertFalse(self.capture._failures.active)
        self.x11.capture.assert_not_called()

    def test_when_the_shared_window_goes_a_window_found_by_name_is_read(self) -> None:
        write(self.path, picture(seed=3))
        self.capture.get()
        self.path.unlink()
        self.assertIs(self.capture.get(), self.x11_frame)
        self.assertEqual(self.capture.backend, OcrCapture.BACKEND_X11)
        self.assertIsNone(self.capture.sharedWindow)
        self.assertFalse(self.capture._failures.active)

    def test_when_the_shared_window_goes_and_nothing_replaces_it_that_is_a_failure(self) -> None:
        for available in (True, False):
            with self.subTest(x11=available):
                capture = OcrCapture(window_title="VRChat")
                capture._window = self.x11
                self.x11.isAvailable.return_value = available
                self.x11.capture.return_value = None  # no window of that name
                write(self.path, picture(seed=3))
                self.assertIsNotNone(capture.get())
                write(self.path, picture(seed=3), instance=0)
                for _ in range(3):
                    self.assertIsNone(capture.get())
                    self.assertIsNone(capture.source)
                    self.assertEqual(capture.sharedWindow, "ended")
                    self.assertTrue(capture._failures.active)
                    self.assertEqual(capture._failures._kind[0], SharedWindowEnded)

    def test_sharing_again_ends_the_failure(self) -> None:
        self.x11.capture.return_value = None
        write(self.path, picture(seed=3))
        self.capture.get()
        self.path.unlink()
        self.assertIsNone(self.capture.get())
        self.assertTrue(self.capture._failures.active)
        again = picture(seed=4)
        write(self.path, again, instance=(4343 << 32) | 1)
        np.testing.assert_array_equal(self.capture.get(), again)
        self.assertEqual(self.capture.sharedWindow, "active")
        self.assertFalse(self.capture._failures.active)

    def test_a_window_that_was_never_shared_is_not_missed(self) -> None:
        self.x11.capture.return_value = None
        for _ in range(3):
            self.assertIsNone(self.capture.get())
        self.assertIsNone(self.capture.sharedWindow)
        self.assertFalse(self.capture._failures.active)

    def test_an_unreadable_frame_is_reported_like_other_capture_errors(self) -> None:
        write(self.path, picture(), layout=9)
        self.assertIsNone(self.capture.get())
        self.assertEqual(self.capture._failures._kind[0], SharedWindowError)

    def test_close_forgets_the_shared_window(self) -> None:
        write(self.path, picture(seed=3))
        self.capture.get()
        self.capture.close()
        self.assertIsNone(self.capture.sharedWindow)
        self.assertEqual(self.capture.backend, OcrCapture.BACKEND_NONE)

    def test_windows_has_no_shared_window(self) -> None:
        write(self.path, picture(seed=3))
        with patch.object(ocr_capture.sys, "platform", "win32"):
            capture = OcrCapture(window_title="VRChat")
        self.assertIsNone(capture._shared)
        self.assertEqual(capture._window_backend, OcrCapture.BACKEND_HWND)


class TestProbe(_Facade):
    def test_a_shared_window_is_enough_to_start(self) -> None:
        write(self.path, picture())
        with patch.object(ocr_capture, "X11WindowCapture") as x11:
            self.assertEqual(probeCapture("VRChat"), CAPTURE_OK)
        x11.assert_not_called()

    def test_without_one_the_x11_answer_stands(self) -> None:
        with patch.object(ocr_capture, "X11WindowCapture") as x11:
            x11.return_value.isAvailable.return_value = False
            self.assertEqual(probeCapture("VRChat"), CAPTURE_UNAVAILABLE)
        x11.return_value.close.assert_called_once()


class TestPipelineReport(_Facade):
    """The worker's status is what the settings page shows while chat reading runs."""

    def setUp(self):
        super().setUp()
        self._patch(ocr_pipeline, "errorLogging")
        self._patch(ocr_pipeline, "printLog")
        self.pipeline = ocr_pipeline.OcrPipeline(callback=Mock(), chatbox_filter=False)
        self.pipeline._reader = Mock()
        self.pipeline._capture = self.capture
        self.pipeline._detector = Mock()
        self.pipeline._detector.detect.return_value = []

    def test_a_lost_shared_window_shows_as_a_capture_failure_and_recovers(self) -> None:
        self.x11.capture.return_value = None
        write(self.path, picture(seed=3))
        self.pipeline._tick()
        self.assertEqual(self.pipeline.runtimeStatus["state"], "reading")
        self.assertEqual(self.capture.sharedWindow, "active")

        self.path.unlink()
        self.pipeline._tick()
        status = self.pipeline.runtimeStatus
        self.assertEqual((status["state"], status["stage"]), ("retrying", "capture"))
        self.assertEqual(status["error_code"], ErrorCode.OCR_DISABLED_CAPTURE_UNAVAILABLE.value)
        self.assertEqual(self.capture.sharedWindow, "ended")
        # Paused, not hammering: the next look waits for the retry time.
        self.assertGreater(self.pipeline._stage_retries["capture"].retry_at, 0)

        write(self.path, picture(seed=5), instance=(4343 << 32) | 1)
        self.pipeline._stage_retries["capture"].retry_at = 0.0
        self.pipeline._tick()
        self.assertEqual(self.pipeline.runtimeStatus["state"], "reading")
        self.assertIsNone(self.pipeline.runtimeStatus["error_code"])

    def test_waiting_for_the_first_frame_is_not_a_failure(self) -> None:
        self.path.write_bytes(header(sequence=0))
        self.pipeline._tick()
        status = self.pipeline.runtimeStatus
        self.assertEqual((status["state"], status["stage"], status["error_code"]), ("waiting", "capture", None))


class TestController(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = Controller.__new__(Controller)
        for name in ("OCR_PORTAL_RESTORE_TOKEN", "ENABLE_OCR_CAPTURE"):
            self.addCleanup(setattr, config, name, getattr(config, name))

    def test_the_restore_token_is_stored_and_read_back(self) -> None:
        self.assertEqual(self.controller.setOcrPortalRestoreToken("0b3c9f2e-token")["result"], "0b3c9f2e-token")
        self.assertEqual(self.controller.getOcrPortalRestoreToken()["result"], "0b3c9f2e-token")
        self.assertEqual(self.controller.setOcrPortalRestoreToken("")["result"], "")
        self.assertEqual(config.OCR_PORTAL_RESTORE_TOKEN, "")

    def test_what_is_not_a_token_is_rejected_and_changes_nothing(self) -> None:
        config.OCR_PORTAL_RESTORE_TOKEN = "kept"
        for value in ("x" * 513, "two\nlines", None, 7, ["token"]):
            response = self.controller.setOcrPortalRestoreToken(value)
            self.assertEqual(response["status"], 400, value)
            self.assertEqual(response["result"]["data"], "kept")
        self.assertEqual(config.OCR_PORTAL_RESTORE_TOKEN, "kept")

    def test_no_token_until_a_window_was_shared(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "config.py").read_text(encoding="utf-8")
        self.assertIn('self._OCR_PORTAL_RESTORE_TOKEN = ""', source)

    def test_endpoints_are_routed(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "mainloop.py").read_text(encoding="utf-8")
        for endpoint, handler in (("/get/data/ocr_portal_restore_token", "getOcrPortalRestoreToken"),
                                  ("/set/data/ocr_portal_restore_token", "setOcrPortalRestoreToken")):
            self.assertIn(f'"{endpoint}": {{"status": True, "variable":controller.{handler}}}', source)

    def test_the_status_says_whether_a_shared_window_is_read(self) -> None:
        config.ENABLE_OCR_CAPTURE = True
        pipeline = Mock(is_alive=True, runtimeStatus={
            "state": "retrying", "stage": "capture", "error_code": "OCR_DISABLED_CAPTURE_UNAVAILABLE", "detector": "region"})
        pipeline._capture = Mock(source=None, sharedWindow="ended")
        with patch("controller.model.ocr_pipeline", pipeline, create=True):
            status = self.controller.getOcrCaptureStatus()["result"]
        self.assertEqual(status["shared_window"], "ended")
        self.assertEqual(status["state"], "retrying")
        config.ENABLE_OCR_CAPTURE = False
        with patch("controller.model.ocr_pipeline", pipeline, create=True):
            self.assertIsNone(self.controller.getOcrCaptureStatus()["result"]["shared_window"])


if __name__ == "__main__":
    unittest.main()
