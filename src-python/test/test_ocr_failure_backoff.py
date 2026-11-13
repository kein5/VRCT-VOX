"""OCR failure diagnostics and cooldowns with fake readers, windows and time."""

from threading import Event, Thread
from types import SimpleNamespace
import traceback
import unittest
from unittest.mock import Mock, patch

import numpy as np

from models.ocr import ocr_capture_hwnd as hwnd
from models.ocr import ocr_capture
from models.ocr import ocr_engine_rapidocr as engine
from models.ocr import ocr_failure, ocr_pipeline


class _Harness(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.tracebacks = []
        self.logs = []
        self.frame = np.zeros((8, 8, 3), dtype=np.uint8)
        self.empty = SimpleNamespace(txts=[], scores=[], boxes=None)
        self._patch(ocr_failure.time, "monotonic", side_effect=lambda: self.now)

    def _patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def _logging(self, module):
        self._patch(module, "errorLogging", side_effect=lambda: self.tracebacks.append(traceback.format_exc()))
        self._patch(module, "printLog", side_effect=self.logs.append)

    def _messages(self, word):
        return [message for message in self.logs if word in message]


class TestTextOnlyReader(_Harness):
    def setUp(self):
        super().setUp()
        self._logging(engine)
        engine._read_failures.reset()
        self.addCleanup(engine._read_failures.reset)

    def test_repeated_reader_failures_are_summarized_and_recovery_is_logged_once(self):
        reader = Mock(side_effect=RuntimeError("broken reader"))
        for tick in range(81):
            self.now = 100 + tick * 0.75
            for _ in range(6):
                self.assertEqual(engine.readtext_bgr(reader, self.frame), [])
        self.assertEqual(len(self.tracebacks), 1)
        self.assertIn("RuntimeError: broken reader", self.tracebacks[0])
        self.assertNotEqual(self.tracebacks[0], "NoneType: None\n")
        self.assertEqual(len(self._messages("suppressed")), 1)
        self.assertIn("suppressed 480 repeated failures", self.logs[0])
        reader.side_effect = None
        reader.return_value = self.empty
        for _ in range(2):
            self.assertEqual(engine.readtext_bgr(reader, self.frame), [])
        self.assertEqual(len(self._messages("recovered")), 1)
        reader.side_effect = RuntimeError("broken reader")
        engine.readtext_bgr(reader, self.frame)
        self.assertEqual(len(self.tracebacks), 2)

    def test_exception_type_or_message_changes_log_a_fresh_traceback(self):
        reader = Mock(side_effect=[RuntimeError("one"), RuntimeError("one"),
                                   RuntimeError("two"), ValueError("two")])
        for _ in range(4):
            self.assertEqual(engine.readtext_bgr(reader, self.frame), [])
        self.assertEqual(len(self.tracebacks), 3)
        self.assertIn("ValueError: two", self.tracebacks[-1])

    def test_strict_boundary_raises_without_logging_but_empty_text_succeeds(self):
        reader = Mock(side_effect=RuntimeError("broken reader"))
        with self.assertRaisesRegex(RuntimeError, "broken reader"):
            engine.readtext_bgr_or_raise(reader, self.frame)
        self.assertEqual(self.tracebacks, [])
        reader.side_effect = None
        reader.return_value = self.empty
        self.assertEqual(engine.readtext_bgr_or_raise(reader, self.frame), [])
        reader.return_value = SimpleNamespace(txts=[" hello "], scores=[0.9], boxes=None)
        self.assertEqual(engine.readtext_bgr(reader, self.frame), [{"text": "hello", "confidence": 0.9}])


class TestPipelineBackoff(_Harness):
    def setUp(self):
        super().setUp()
        self._logging(ocr_pipeline)
        self.pipeline = ocr_pipeline.OcrPipeline(callback=Mock(), chatbox_filter=False)
        self.reader = Mock(side_effect=RuntimeError("broken reader"))
        self.capture = Mock()
        self.capture.get.return_value = self.frame
        self.pipeline._reader = self.reader
        self.pipeline._capture = self.capture
        self.pipeline._detector = Mock()
        # Distinct pixels keep the six-candidate recovery check independent of reuse.
        self.pipeline._detector.detect.return_value = [
            ((0, 0, 8, 8), np.full_like(self.frame, i)) for i in range(6)]

    def _fail_three_times(self):
        for _ in range(3):
            self.pipeline._tick()
            self.now += 0.75

    def test_simulated_minute_limits_work_and_preserves_status_summaries(self):
        for tick in range(80):
            self.now = 100 + tick * 0.75
            self.pipeline._tick()
        self.assertEqual(self.reader.call_count, 8)
        self.assertEqual(len(self.tracebacks), 1)
        self.assertIn("RuntimeError: broken reader", self.tracebacks[0])
        self.assertEqual(self._messages("suppressed"), [])
        self.now = 160
        self.pipeline._tick()  # The summary is due even during cooldown.
        self.assertEqual(self.reader.call_count, 8)
        self.assertEqual(len(self._messages("suppressed")), 1)
        self.assertIn("suppressed 7 repeated failures", self._messages("suppressed")[0])
        self.assertEqual(len(self._messages("OCR status (30s)")), 2)
        self.pipeline._callback.assert_not_called()

    def test_backoff_skips_capture_detection_and_all_crops_and_is_capped(self):
        self._fail_three_times()
        self.assertEqual(self.reader.call_count, 3)  # One attempt per failed tick, not six.
        for delay in (1, 2, 4, 8, 16, 30, 30):
            retry_at = self.pipeline._engine_retry_at
            self.assertEqual(self.pipeline._engine_backoff, delay)
            self.now = retry_at - 0.001
            calls = (self.reader.call_count, self.capture.get.call_count,
                     self.pipeline._detector.detect.call_count)
            self.pipeline._tick()
            self.assertEqual(calls, (self.reader.call_count, self.capture.get.call_count,
                                     self.pipeline._detector.detect.call_count))
            self.now = retry_at
            self.pipeline._tick()
            self.assertEqual(self.reader.call_count, calls[0] + 1)

    def test_empty_success_clears_backoff_and_recovery_is_logged_once(self):
        self._fail_three_times()
        self.now = self.pipeline._engine_retry_at
        self.reader.side_effect = None
        self.reader.return_value = self.empty
        self.pipeline._tick()
        self.assertEqual(self.pipeline._engine_retry_at, 0)
        self.assertEqual(self.pipeline._engine_failure_count, 0)
        self.assertEqual(self.reader.call_count, 9)  # All six candidates resume immediately.
        self.pipeline._tick()
        self.assertEqual(len(self._messages("recovered")), 1)
        self.reader.side_effect = RuntimeError("broken reader")
        self.now += ocr_pipeline.RECOGNITION_REFRESH_SEC  # Force a real health probe.
        self.pipeline._tick()
        self.assertEqual(len(self.tracebacks), 2)
        self.assertEqual(self.pipeline._engine_backoff, 0)

    def test_missing_frames_do_not_reset_an_engine_failure(self):
        self.pipeline._tick()
        self.capture.get.return_value = None
        self.pipeline._tick()
        self.assertEqual(self.pipeline._engine_failure_count, 1)
        self.assertEqual(self._messages("recovered"), [])

    def test_new_failure_kind_logs_again_without_evading_backoff(self):
        self.reader.side_effect = [RuntimeError("one"), ValueError("two"), ValueError("two")]
        self._fail_three_times()
        self.assertEqual(len(self.tracebacks), 2)
        self.assertEqual(self.pipeline._engine_backoff, 1)

    def test_stop_restart_clears_failure_history_and_cooldown(self):
        self._fail_three_times()
        self.assertTrue(self.pipeline.stop())
        self.assertEqual(self.pipeline._engine_retry_at, 0)
        self._patch(ocr_pipeline.ocr_engine, "isAvailable", return_value=True)
        self._patch(self.pipeline, "_readerFor", return_value=self.reader)
        self._patch(self.pipeline, "_capture_probe", return_value=ocr_pipeline.CAPTURE_OK)
        self._patch(ocr_pipeline, "BackgroundThreads")
        self._patch(ocr_pipeline, "Thread")
        self.assertTrue(self.pipeline.start())
        self.assertFalse(self.pipeline._stop_event.is_set())
        self.pipeline._capture = self.capture
        self.pipeline._tick()
        self.assertEqual(self.reader.call_count, 4)
        self.assertEqual(len(self.tracebacks), 2)
        self.assertEqual(self.pipeline._engine_backoff, 0)
        self.assertEqual(self._messages("recovered"), [])

    def test_a_different_reader_can_be_tried_without_waiting_for_old_cooldown(self):
        self._fail_three_times()
        replacement = Mock(return_value=self.empty)
        self._patch(self.pipeline, "_readerFor", return_value=replacement)
        self.pipeline.applyConfig({"source_language": "Korean"})
        self.pipeline._applyPending()
        self.pipeline._tick()
        self.assertEqual(replacement.call_count, 6)
        self.assertEqual(self.pipeline._engine_retry_at, 0)

    def test_generic_tick_exceptions_are_suppressed_and_recover(self):
        # Exercise the real worker catch with a fake interruptible tick clock.
        stop = Mock()
        stop.is_set.return_value = False

        def wait(seconds):
            self.now += seconds
            if self.now >= 222:
                stop.is_set.return_value = True

        stop.wait.side_effect = wait
        self.pipeline._stop_event = stop
        self.pipeline._poll_interval = 1
        self._patch(ocr_pipeline, "OcrCapture", return_value=self.capture)
        self._patch(ocr_pipeline, "lowerCurrentThread")

        def tick():
            if self.now < 161:
                raise RuntimeError("tick failure")
            if self.now < 221:
                raise ValueError("different failure")

        tick_call = self._patch(self.pipeline, "_tick", side_effect=tick)
        self.pipeline._run()
        self.assertEqual(len(self.tracebacks), 2)
        self.assertEqual(len(self._messages("suppressed")), 2)
        self.assertIn("suppressed 5 repeated failures", self._messages("suppressed")[0])
        self.assertIn("suppressed 1 repeated failures", self._messages("suppressed")[1])
        self.assertEqual(tick_call.call_count, 9)  # 1, 2, 4, ... 30s retry schedule.
        self.assertEqual(len(self._messages("recovered")), 1)
        self.capture.close.assert_called_once()

    def test_delivery_exceptions_use_tick_backoff_and_retry_until_accepted(self):
        self.reader.side_effect = None
        self.reader.return_value = SimpleNamespace(txts=["hello world"], scores=[1.0], boxes=None)
        self.pipeline._detector.detect.return_value = [((0, 0, 8, 8), self.frame)]
        callback = self.pipeline._callback
        callback.side_effect = RuntimeError("delivery failed")
        stop = Mock()
        stop.is_set.return_value = False
        snapshots = []

        def wait(seconds):
            snapshots.append((self.now, self.pipeline.runtimeStatus, callback.call_count,
                              len(self.pipeline._dedup._items)))
            self.now += seconds
            if self.now >= 161:
                callback.side_effect = None
                callback.return_value = True
            if self.now >= 194:
                stop.is_set.return_value = True

        stop.wait.side_effect = wait
        self.pipeline._stop_event = stop
        self.pipeline._poll_interval = 1
        self._patch(ocr_pipeline, "lowerCurrentThread")
        self.pipeline._run()
        failures = [row for row in snapshots if row[0] < 161]
        self.assertTrue(all(row[1]["state"] == "retrying" for row in failures))
        self.assertTrue(all(row[1]["stage"] == "tick" for row in failures))
        self.assertTrue(all(row[1]["error_code"] == "OCR_DISABLED_UNKNOWN" for row in failures))
        self.assertTrue(all(row[3] == 0 for row in failures))
        self.assertEqual(failures[-1][2], 6)  # Attempts at 100, 101, 103, 107, 115, 131.
        self.assertEqual(callback.call_count, 7)  # Recovery at 161, then deduplication.
        self.assertEqual(len(self.tracebacks), 1)
        self.assertEqual(len(self._messages("suppressed")), 1)
        self.assertEqual(len(self._messages("recovered")), 1)
        self.assertEqual(snapshots[-1][1]["state"], "reading")
        self.assertEqual(snapshots[-1][3], 1)


class TestResponsiveStop(unittest.TestCase):
    def test_stop_wakes_the_worker_during_a_thirty_second_cooldown(self):
        waiting = Event()

        class StopEvent(Event):
            def wait(self, timeout=None):
                waiting.set()
                return super().wait(timeout)

        pipeline = ocr_pipeline.OcrPipeline(callback=Mock(), poll_interval_ms=30000)
        pipeline._stop_event = StopEvent()
        pipeline._engine_retry_at = float("inf")
        capture = Mock()
        with patch.object(ocr_pipeline, "OcrCapture", return_value=capture), \
                patch.object(ocr_pipeline, "lowerCurrentThread"):
            pipeline._thread = Thread(target=pipeline._run, daemon=True)
            pipeline._thread.start()
            try:
                self.assertTrue(waiting.wait(2))
                stopped = Event()
                result = []

                def stop():
                    result.append(pipeline.stop())
                    stopped.set()

                stopper = Thread(target=stop, daemon=True)
                stopper.start()
                self.assertTrue(stopped.wait(1), "stop must wake Event.wait, not await the cooldown")
                stopper.join(1)
                self.assertEqual(result, [True])
            finally:
                pipeline._stop_event.set()
                pipeline.stop()
        capture.get.assert_not_called()
        capture.close.assert_called_once()


class TestHwndFailures(_Harness):
    def setUp(self):
        super().setUp()
        self._logging(hwnd)
        self.capture = hwnd.HwndCapture()
        self._patch(self.capture, "isAvailable", return_value=True)
        self._patch(hwnd, "_find_vrchat_hwnd", return_value=42)
        self._patch(hwnd, "_window_rect", return_value=(0, 0, 8, 8))
        self.iconic = self._patch(hwnd, "_is_iconic", return_value=False)
        self.print_window = self._patch(hwnd, "_print_window", side_effect=OSError("capture failed"))

    def test_repeats_are_summarized_and_only_a_frame_means_recovery(self):
        for tick in range(81):
            self.now = 100 + tick * 0.75
            self.assertIsNone(self.capture.capture())
        self.assertEqual(len(self.tracebacks), 1)
        self.assertIn("OSError: capture failed", self.tracebacks[0])
        self.assertEqual(len(self._messages("suppressed")), 1)
        self.print_window.side_effect = None
        self.print_window.return_value = None
        self.capture.capture()
        self.iconic.return_value = True
        self.capture.capture()
        self.assertEqual(self._messages("recovered"), [])
        self.iconic.return_value = False
        self.print_window.return_value = self.frame
        self.assertIs(self.capture.capture(), self.frame)
        self.capture.capture()
        self.assertEqual(len(self._messages("recovered")), 1)

    def test_different_kind_and_close_each_allow_a_fresh_traceback(self):
        self.capture.capture()
        self.print_window.side_effect = ValueError("bad bitmap")
        self.capture.capture()
        self.capture.capture()
        self.assertEqual(len(self.tracebacks), 2)
        self.capture.close()
        self.capture.capture()
        self.assertEqual(len(self.tracebacks), 3)
        self.assertEqual(self._messages("recovered"), [])


class TestCaptureFacadeFailures(_Harness):
    def test_backend_exceptions_do_not_bypass_suppression(self):
        self._logging(ocr_capture)
        window = Mock()
        window.capture.side_effect = RuntimeError("window lookup failed")
        self._patch(ocr_capture, "_windowCapture", return_value=("hwnd", window))
        self._patch(ocr_capture, "_isSteamvrRunning", return_value=False)
        capture = ocr_capture.OcrCapture()
        for tick in range(81):
            self.now = 100 + tick * 0.75
            self.assertIsNone(capture.get())
        self.assertEqual(len(self.tracebacks), 1)
        self.assertEqual(len(self._messages("suppressed")), 1)
        window.capture.side_effect = ValueError("bad frame")
        capture.get()
        self.assertEqual(len(self.tracebacks), 2)
        window.capture.side_effect = None
        window.capture.return_value = None
        capture.get()
        self.assertEqual(self._messages("recovered"), [])
        self._patch(ocr_capture, "isFrameBlank", return_value=False)
        window.capture.return_value = self.frame
        self.assertIs(capture.get(), self.frame)
        capture.get()
        self.assertEqual(len(self._messages("recovered")), 1)
        window.capture.side_effect = ValueError("bad frame")
        capture.get()
        capture.close()
        self.now += 5  # The facade reselects a backend on its existing five-second timer.
        capture.get()
        self.assertEqual(len(self.tracebacks), 4)


if __name__ == "__main__":
    unittest.main()
