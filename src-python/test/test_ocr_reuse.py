"""Recognition reuse with synthetic pixels, fake readers/capture and a fake clock."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from models.ocr import ocr_pipeline


class _Capture:
    def __init__(self, frame):
        self.frame = frame
        self.backend = "x11"

    def get(self):
        return self.frame

    def close(self):
        pass


class TestRecognitionReuse(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.logs = []
        self.received = []
        self.frame = np.full((24, 64, 3), 20, dtype=np.uint8)
        self.capture = _Capture(self.frame)
        self.result = SimpleNamespace(txts=["hello world"], scores=[0.9], boxes=None)
        self.reader = Mock(return_value=self.result)
        self.detector = Mock(splits_bubbles=False, confidence=0.7)
        self.candidates = [((0, 0, 64, 24), self.frame)]
        self.detector.detect.side_effect = lambda frame: self.candidates
        self.pipeline = ocr_pipeline.OcrPipeline(
            callback=self.received.append, detector=self.detector, chatbox_filter=False)
        self.pipeline._reader = self.reader
        self.pipeline._capture = self.capture
        self._patch(ocr_pipeline.time, "monotonic", side_effect=lambda: self.now)
        self._patch(ocr_pipeline, "printLog", side_effect=self.logs.append)
        self.tracebacks = self._patch(ocr_pipeline, "errorLogging")

    def _patch(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def _tick(self, seconds=0.75):
        self.now += seconds
        self.pipeline._tick()

    def _prime(self):
        self.pipeline._tick()
        self._tick()
        self.assertEqual(self.reader.call_count, 1)

    def _configure(self, settings):
        self.pipeline.applyConfig(settings)
        self.pipeline._applyPending()

    def test_identical_pixels_in_a_new_array_reuse_words_and_still_deduplicate(self):
        self.pipeline._tick()
        self.candidates = [((10, 0, 64, 24), self.frame.copy())]
        self._tick()
        self.assertEqual(self.reader.call_count, 1)
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.pipeline._counts["ocr"], 1)
        self.assertEqual(self.pipeline._counts["reused"], 1)
        self.assertEqual(self.pipeline._counts["text"], 2)
        self.assertEqual(self.pipeline._counts["bubble"], 2)
        self.assertEqual(self.detector.detect.call_count, 2)  # Detection is never cached.

    def test_one_changed_pixel_in_the_same_array_reads_again(self):
        self._prime()
        self.frame[-1, -1, -1] += 1
        self._tick()
        self.assertEqual(self.reader.call_count, 2)

    def test_shape_and_dtype_are_part_of_the_pixel_key(self):
        self._prime()
        for crop in (self.frame.reshape(48, 32, 3), self.frame.view(np.int8)):
            self.assertEqual(crop.tobytes(), self.frame.tobytes())
            self.candidates = [((0, 0, 64, 24), crop)]
            self._tick()
        self.assertEqual(self.reader.call_count, 3)

    def test_strided_crops_match_contiguous_copies_but_detect_pixel_changes(self):
        crop = self.frame[:, ::2, ::-1]
        self.candidates = [((0, 0, 32, 24), crop)]
        self.pipeline._tick()
        self.candidates = [((0, 0, 32, 24), crop.copy())]
        self._tick()
        self.assertEqual(self.reader.call_count, 1)
        crop[-1, -1, -1] += 1
        self.candidates = [((0, 0, 32, 24), crop)]
        self._tick()
        self.assertEqual(self.reader.call_count, 2)

    def test_language_changes_invalidate_even_when_the_reader_and_model_are_shared(self):
        self._prime()
        self._patch(self.pipeline, "_readerFor", return_value=self.reader)
        for language in ("Japanese", "Korean", "auto"):
            self._configure({"source_language": language})
            self._tick()
        self.assertEqual(self.reader.call_count, 4)

    def test_reader_identity_change_reads_again(self):
        self._prime()
        replacement = Mock(return_value=self.result)
        self.pipeline._reader = replacement
        self._tick()
        replacement.assert_called_once()
        self.pipeline._reader = self.reader
        self._tick()
        self.assertEqual(self.reader.call_count, 2)

    def test_model_spec_and_root_changes_invalidate(self):
        self._prime()
        self._patch(ocr_pipeline, "resolveModelSpec", return_value=object())
        self._tick()
        self.pipeline._model_root = "another-model-root"
        self._tick()
        self.assertEqual(self.reader.call_count, 3)

    def test_scalar_and_region_settings_invalidate_even_with_identical_crops(self):
        self._prime()
        for settings in (
            {"min_confidence": 0.99}, {"min_text_length": 50},
            {"poll_interval_ms": 100}, {"chatbox_filter": True},
            {"region": (0.1, 0.1, 0.8, 0.8)},
        ):
            with self.subTest(settings=settings):
                previous = self.reader.call_count
                self._configure(settings)
                self._tick()
                self.assertEqual(self.reader.call_count, previous + 1)

    def test_detector_replacement_and_reconfiguration_invalidate(self):
        self._prime()
        replacement = Mock(splits_bubbles=False)
        replacement.detect.side_effect = lambda frame: self.candidates
        for detector in (replacement, replacement, self.detector):
            self._configure({"detector": detector})
            self._tick()
        self.assertEqual(self.reader.call_count, 4)

    def test_builtin_detector_setting_changes_are_not_reused(self):
        self._prime()
        for name, value in (("confidence", 0.8), ("crop_padding", 8), ("nms_iou", 0.6),
                            ("image_size", 320), ("model_path", "another.onnx"), ("max_side", 640)):
            with self.subTest(name=name):
                previous = self.reader.call_count
                setattr(self.detector, name, value)
                self._tick()
                self.assertEqual(self.reader.call_count, previous + 1)

    def test_capture_title_and_capture_identity_changes_invalidate(self):
        self._prime()
        self._patch(ocr_pipeline, "OcrCapture", return_value=self.capture)
        self._configure({"window_title": "Another VRChat"})
        self._tick()
        self.pipeline._capture = _Capture(self.frame)
        self._tick()
        self.assertEqual(self.reader.call_count, 3)

    def test_backend_change_during_get_invalidates_in_both_directions(self):
        self._prime()
        for backend in ("openvr_mirror", "x11"):
            def get():
                self.capture.backend = backend
                return self.frame
            self.capture.get = get
            self._tick()
        self.assertEqual(self.reader.call_count, 3)

    def test_missing_frame_discards_recognition_without_marking_text_seen(self):
        self._prime()
        seen_at = next(iter(self.pipeline._dedup._items.values()))[0]
        self.capture.frame = None
        self._tick()
        self.assertEqual(len(self.pipeline._recognition._items), 0)
        self.assertEqual(next(iter(self.pipeline._dedup._items.values()))[0], seen_at)
        self.capture.frame = self.frame
        self._tick()
        self.assertEqual(self.reader.call_count, 2)

    def _fakeStart(self):
        self._patch(self.pipeline, "isEngineAvailable", return_value=True)
        self._patch(self.pipeline, "_readerFor", return_value=self.reader)
        self._patch(self.pipeline, "_capture_probe", return_value=ocr_pipeline.CAPTURE_OK)
        self._patch(ocr_pipeline, "BackgroundThreads")
        self._patch(ocr_pipeline, "Thread")
        self.assertTrue(self.pipeline.start())
        self.pipeline._capture = self.capture

    def test_stop_and_start_discard_recognition_even_with_the_same_reader_and_capture(self):
        self._prime()
        self.assertTrue(self.pipeline.stop())
        self.assertEqual(len(self.pipeline._recognition._items), 0)
        self._fakeStart()
        self._tick()
        self.assertEqual(self.reader.call_count, 2)

    def test_start_itself_discards_recognition(self):
        self._prime()
        self._fakeStart()
        self.assertEqual(len(self.pipeline._recognition._items), 0)
        self._tick()
        self.assertEqual(self.reader.call_count, 2)

    def test_periodic_refresh_is_measured_from_read_not_last_hit(self):
        self.pipeline._tick()
        for second in range(1, 20):
            self._tick(seconds=1)
        self.assertEqual(self.reader.call_count, 1)
        self.reader.return_value = SimpleNamespace(txts=["a different message"], scores=[0.9], boxes=None)
        self._tick(seconds=1)
        self.assertEqual(self.reader.call_count, 2)
        self.assertEqual([p["text"] for p in self.received], ["hello world", "a different message"])

    def test_empty_success_is_cached_but_also_refreshed(self):
        self.reader.return_value = SimpleNamespace(txts=[], scores=[], boxes=None)
        self._prime()
        self.assertEqual(self.received, [])
        self.assertEqual(self.pipeline._counts["text"], 0)
        self._tick(seconds=20)
        self.assertEqual(self.reader.call_count, 2)

    def test_reuse_refreshes_seen_for_longer_than_retention(self):
        for second in range(91):
            self.now = 100 + second
            self.pipeline._tick()
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.reader.call_count, 5)
        self.assertEqual(next(iter(self.pipeline._dedup._items.values()))[0], 190)

    def test_disappearance_and_reappearance_match_uncached_delivery(self):
        # Keep a different bubble visible while the original is absent. This
        # preserves the existing slow-tick retention floor as well as the >30s boundary.
        original = self.candidates[0]
        other = ((0, 0, 64, 24), np.full_like(self.frame, 40))
        self.reader.side_effect = lambda crop: self.result if crop[0, 0, 0] == 20 else SimpleNamespace(
            txts=["a different message"], scores=[0.9], boxes=None)
        deliveries = []
        for reuse in (False, True):
            self.pipeline._dedup = ocr_pipeline._DedupCache()
            self.pipeline._resetRecognition()
            self.pipeline._last_tick_at = 0.0
            self.received.clear()
            for second in range(102):
                self.now = 100 + second
                # Last seen 39; return at 69 (exactly 30s), then at 100 (>30s).
                self.candidates = [original] if second < 40 or second in (69, 100) else [other]
                if not reuse:
                    self.pipeline._resetRecognition()
                self.pipeline._tick()
            deliveries.append([p["text"] for p in self.received])
        self.assertEqual(deliveries[0], ["hello world", "a different message", "hello world"])
        self.assertEqual(deliveries[1], deliveries[0])

    def test_no_candidate_gap_expires_delivery_after_thirty_seconds(self):
        self._prime()
        self.candidates = []
        for _ in range(40):
            self._tick(seconds=1)
        self.candidates = [((0, 0, 64, 24), self.frame)]
        self._tick()
        # Empty ticks are real cadence samples. An absence is not a slow
        # recognition tick and must not extend retention to twice that absence.
        self.assertEqual(len(self.received), 2)

    def test_no_frame_gap_also_expires_delivery(self):
        self._prime()
        self.capture.frame = None
        for _ in range(40):
            self._tick(seconds=1)
        self.assertEqual(len(self.pipeline._dedup._items), 0)
        self.capture.frame = self.frame
        self._tick()
        self.assertEqual(len(self.received), 2)

    def test_changing_slow_first_crop_does_not_starve_the_second(self):
        attempted = []

        def read(crop):
            attempted.append(int(crop[0, 0, 0]))
            self.now += 0.7  # More than the 0.6s budget, using a fake clock.
            text = "second bubble is readable" if attempted[-1] == 99 else "first bubble keeps changing"
            return SimpleNamespace(txts=[text], scores=[0.9], boxes=None)

        self.reader.side_effect = read
        for tick in range(12):
            self.candidates = [((0, 0, 64, 24), np.full_like(self.frame, tick)),
                               ((80, 0, 64, 24), np.full_like(self.frame, 99))]
            self._tick()
        self.assertIn(99, attempted[:2])
        self.assertTrue(any(payload["text"] == "second bubble is readable" for payload in self.received))
        self.assertLessEqual(len(attempted), 12)

    def test_activation_gates_first_tick_and_rejected_delivery_is_retried(self):
        active = False
        self.pipeline._activation_ready = lambda: active
        self.pipeline._tick()
        self.reader.assert_not_called()
        self.assertFalse(self.pipeline._dedup._items)
        active = True
        self.pipeline._callback = Mock(return_value=False)
        self._tick()
        self.assertFalse(self.pipeline._dedup._items)
        self.assertEqual(self.pipeline._counts["emit"], 0)
        self.pipeline._callback = self.received.append
        self._tick()
        self._tick()
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.reader.call_count, 1)  # Recognition reuse still applies.

    def test_confidence_reordering_and_small_motion_do_not_starve_a_bubble(self):
        attempted = []

        def read(crop):
            attempted.append(int(crop[0, 0, 0]))
            self.now += 0.7
            return self.result

        self.reader.side_effect = read
        for tick in range(12):
            self.candidates = [((tick, 0, 64, 24), np.full_like(self.frame, tick)),
                               ((80 + tick, 0, 64, 24), np.full_like(self.frame, 99))]
            if tick % 2:
                self.candidates.reverse()
            self._tick()
        self.assertIn(99, attempted[:2])
        self.assertLessEqual(len(attempted), 12)

    def test_slow_rotation_keeps_visible_messages_but_expires_absent_text(self):
        texts = ["alpha message", "bravo reply", "charlie talks", "delta speaks",
                 "echo greeting", "foxtrot says goodbye"]
        crops = [((i * 80, 0, 64, 24), np.full_like(self.frame, i)) for i in range(6)]
        self.candidates = crops

        def read(crop):
            self.now += 6  # A full six-candidate rotation takes over 30 seconds.
            return SimpleNamespace(txts=[texts[int(crop[0, 0, 0])]], scores=[0.9], boxes=None)

        self.reader.side_effect = read
        for _ in range(18):
            self._tick()
        self.assertEqual([p["text"] for p in self.received], texts)
        # Changing the pixels must not keep the old text alive at the same box.
        self.candidates = [((0, 0, 64, 24), np.full_like(self.frame, 1))]
        for _ in range(40):
            self._tick(seconds=1)
        self.assertNotIn(ocr_pipeline._textHash(texts[0]), self.pipeline._dedup._items)
        self.candidates = crops[:1]
        self._tick()
        self.assertEqual([p["text"] for p in self.received], texts + texts[:1])

    def test_distinct_short_replies_are_delivered_and_exact_repeats_are_not(self):
        for index, text in enumerate(("はい", "いや", "はい", "いや")):
            self.frame[0, 0, 0] = index
            self.reader.return_value = SimpleNamespace(txts=[text], scores=[1.0], boxes=None)
            self._tick()
        self.assertEqual([p["text"] for p in self.received], ["はい", "いや"])

    def test_callback_exception_does_not_mark_a_delivery(self):
        self.pipeline._callback = Mock(side_effect=RuntimeError("callback failed"))
        # The worker handles processing exceptions with its tick retry policy.
        with self.assertRaisesRegex(RuntimeError, "callback failed"):
            self.pipeline._tick()
        self.assertFalse(self.pipeline._dedup._items)
        self.pipeline._callback = self.received.append
        self._tick()
        self.assertEqual(len(self.received), 1)

    def test_deferred_candidate_must_still_be_present_in_current_frame(self):
        def slow_read(crop):
            self.now += 0.7
            return self.result

        self.reader.side_effect = slow_read
        self.candidates = [self.candidates[0], ((80, 0, 64, 24), np.full_like(self.frame, 99))]
        self._tick()
        self.candidates = self.candidates[:1]
        self._tick()
        self.assertEqual(self.reader.call_count, 1)  # Only the current, cached first crop.
        self.assertEqual(len(self.received), 1)

    def test_cached_near_duplicate_refreshes_the_original_seen_timestamp(self):
        self.pipeline._tick()
        self.frame[0, 0, 0] += 1
        self.reader.return_value = SimpleNamespace(txts=["hallo world"], scores=[0.9], boxes=None)
        for _ in range(40):
            self._tick(seconds=1)
        self.assertEqual(len(self.received), 1)
        self.assertEqual(len(self.pipeline._dedup._items), 1)
        self.assertEqual(next(iter(self.pipeline._dedup._items.values()))[:2], (140, "hello world"))

    def test_failure_drops_all_cached_successes_and_backoff_still_engages(self):
        self._prime()
        cached = self.candidates[0]
        changed = ((0, 0, 64, 24), np.full_like(self.frame, 40))
        self.candidates = [cached, changed]
        self.reader.side_effect = RuntimeError("broken reader")
        self._tick()  # Cached first crop succeeds, but the new crop fails.
        self.assertEqual(self.pipeline._engine_failure_count, 1)
        self.assertEqual(len(self.pipeline._recognition._items), 0)
        self.candidates = [cached]
        for _ in range(2):
            self._tick()
        self.assertEqual(self.reader.call_count, 4)
        self.assertEqual(self.pipeline._engine_failure_count, 3)
        self.assertEqual(self.pipeline._engine_backoff, 1)
        self.assertEqual(self.tracebacks.call_count, 1)
        self.assertFalse(any("recovered" in log for log in self.logs))
        calls = self.detector.detect.call_count
        self._tick(seconds=0.1)
        self.assertEqual(self.reader.call_count, 4)
        self.assertEqual(self.detector.detect.call_count, calls)
        self.now = self.pipeline._engine_retry_at
        self.pipeline._tick()
        self.assertEqual(self.reader.call_count, 5)
        self.assertEqual(self.pipeline._engine_backoff, 2)
        self.now = self.pipeline._engine_retry_at
        self.reader.side_effect = None
        self.pipeline._tick()
        self._tick()
        self.assertEqual(self.reader.call_count, 6)
        self.assertEqual(self.pipeline._engine_failure_count, 0)
        self.assertEqual(sum("recovered" in log for log in self.logs), 1)

    def test_refresh_failure_never_falls_back_to_expired_words(self):
        self._prime()
        self.reader.side_effect = RuntimeError("broken reader")
        self.now = 120
        self.pipeline._tick()
        self.assertEqual(self.pipeline._counts["text"], 2)
        self.assertEqual(len(self.pipeline._recognition._items), 0)
        self._tick()
        self.assertEqual(self.reader.call_count, 3)
        self.assertEqual(self.pipeline._engine_failure_count, 2)

    def test_lru_is_bounded_and_hits_protect_recent_entries(self):
        crops = [np.full_like(self.frame, i) for i in range(33)]
        for crop in crops[:32]:
            self.candidates = [((0, 0, 64, 24), crop)]
            self.pipeline._tick()
        self.candidates = [((0, 0, 64, 24), crops[0])]
        self.pipeline._tick()  # Protect the oldest entry.
        self.candidates = [((0, 0, 64, 24), crops[32])]
        self.pipeline._tick()
        self.assertEqual(len(self.pipeline._recognition._items), 32)
        self.candidates = [((0, 0, 64, 24), crops[0])]
        self.pipeline._tick()
        self.assertEqual(self.reader.call_count, 33)
        self.candidates = [((0, 0, 64, 24), crops[1])]
        self.pipeline._tick()  # Evicted entry must be read again.
        self.assertEqual(self.reader.call_count, 34)
        self.assertEqual(len(self.pipeline._recognition._items), 32)

    def test_status_distinguishes_engine_calls_from_reuse(self):
        self._prime()
        self.pipeline._logStatus(130)
        status = next(log for log in self.logs if "OCR status" in log)
        self.assertIn("tick=2 frame=2 candidate=2 ocr=1 reused=1 text=2 bubble=2 emit=1", status)
        self.assertTrue(all(count == 0 for count in self.pipeline._counts.values()))

    def test_static_scene_reader_calls_per_simulated_minute(self):
        for interval_ms, baseline in ((750, 480), (100, 3600)):
            for reuse in (False, True):
                with self.subTest(interval_ms=interval_ms, reuse=reuse):
                    self.pipeline._resetRecognition()
                    self.reader.reset_mock()
                    self.pipeline._poll_interval = interval_ms / 1000
                    self.pipeline._tick_budget = self.pipeline._poll_interval * ocr_pipeline.TICK_OCR_BUDGET_RATIO
                    self.candidates = [((0, 0, 64, 24), np.full_like(self.frame, i)) for i in range(6)]
                    ticks = 60000 // interval_ms
                    for tick in range(ticks):
                        self.now = 100 + tick * interval_ms / 1000
                        if not reuse:
                            self.pipeline._resetRecognition()
                        self.pipeline._tick()
                    self.assertEqual(self.reader.call_count, 18 if reuse else baseline)


if __name__ == "__main__":
    unittest.main()
