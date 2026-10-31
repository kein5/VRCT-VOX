"""The OCR pipeline without a chat-bubble detector.

Capture and the OCR engine are mocked with synthetic frames, except in the
opt-in real-engine test (set VRCT_OCR_MODEL_ROOT to a downloaded_models
directory holding the PP-OCR catalog entries).
"""

import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import numpy as np

from errors import ErrorCode, OcrStartError
from models.ocr import ocr_pipeline
from models.ocr.ocr_capture import CAPTURE_OK, CAPTURE_UNAVAILABLE, CAPTURE_WINDOW_NOT_FOUND
from models.ocr.ocr_detection import RegionCandidates
from models.ocr.ocr_pipeline import OcrPipeline
from ocr_synthetic import Scene, shifted


def _scene():
    scene = Scene()
    scene.bubble(360, 120, ["こんにちは、元気ですか？", "今日はどこ行く？"])
    scene.bubble(960, 140, ["Hello there!", "How are you?"])
    scene.sign(420, 560, "WELCOME TO THE CLUB")
    return scene


class _FakeCapture:
    def __init__(self, frame):
        self.frame = frame
        self.closed = False

    def get(self):
        return self.frame

    def close(self):
        self.closed = True


def _fake_ocr(scene):
    """readtext_bgr stand-in: the scene's lines that fall inside the crop."""
    import cv2
    frame = scene.bgr()

    def read(reader, crop, min_confidence):
        # Locate the crop in the frame (the world background is noise, so a
        # corner patch matches in exactly one place).
        patch_ = crop[:24, :24]
        _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(frame, patch_, cv2.TM_CCOEFF_NORMED))
        if score < 0.99 or not np.array_equal(frame[dy:dy + crop.shape[0], dx:dx + crop.shape[1]], crop):
            return []
        inside = [line for line in scene.lines
                  if line["left"] >= dx and line["right"] <= dx + crop.shape[1]
                  and line["top"] >= dy and line["bottom"] <= dy + crop.shape[0]]
        return shifted(inside, dx, dy)
    return read


class _Harness(unittest.TestCase):
    def _pipeline(self, received, **kwargs):
        return OcrPipeline(callback=received.append, source_language="auto", poll_interval_ms=100,
                           min_confidence=0.5, capture_probe=lambda title: CAPTURE_OK, **kwargs)

    def _run(self, pipeline, scene, received, expected_count, extra_patches=()):
        capture = _FakeCapture(scene.bgr())
        patches = [
            patch.object(ocr_pipeline, "resolveModelFiles", return_value="files"),
            patch.object(ocr_pipeline.ocr_engine, "isAvailable", return_value=True),
            patch.object(ocr_pipeline.ocr_engine, "getReader", return_value=object()),
            patch.object(ocr_pipeline.ocr_engine, "readtext_bgr", side_effect=_fake_ocr(scene)),
            patch.object(ocr_pipeline, "OcrCapture", return_value=capture),
            *extra_patches,
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertTrue(pipeline.start())
        try:
            deadline = time.monotonic() + 5
            while len(received) < expected_count and time.monotonic() < deadline:
                time.sleep(0.02)
            time.sleep(0.25)  # a few more ticks: nothing new may arrive (dedup)
        finally:
            pipeline.stop()
        self.assertTrue(capture.closed)
        return [payload["text"] for payload in received]


class TestRunsWithoutDetector(_Harness):
    def test_default_pipeline_reads_bubbles_and_drops_world_text(self) -> None:
        received = []
        pipeline = self._pipeline(received)
        self.assertIsInstance(pipeline._detector, RegionCandidates)
        texts = self._run(pipeline, _scene(), received, expected_count=2)
        self.assertEqual(sorted(texts), sorted(["こんにちは、元気ですか？\n今日はどこ行く？", "Hello there!\nHow are you?"]))
        self.assertTrue(all(payload["source"] == "ocr" and payload["is_final"] for payload in received))

    def test_chatbox_filter_off_also_reads_world_text(self) -> None:
        received = []
        texts = self._run(self._pipeline(received, chatbox_filter=False), _scene(), received, expected_count=3)
        self.assertIn("WELCOME TO THE CLUB", texts)
        self.assertEqual(len(texts), 3)

    def test_region_limits_what_is_read(self) -> None:
        received = []
        # Right half only: the English bubble.
        pipeline = self._pipeline(received, region={"x": 0.5, "y": 0.0, "width": 0.5, "height": 0.5})
        texts = self._run(pipeline, _scene(), received, expected_count=1)
        self.assertEqual(texts, ["Hello there!\nHow are you?"])

    def test_the_upstream_detector_is_not_used(self) -> None:
        self.assertNotIn("BubbleDetector", vars(ocr_pipeline))
        self.assertNotIn("ocr_bubble_detector", ocr_pipeline.__dict__.get("__file__", ""))


class TestPluggableDetector(_Harness):
    class _OneBubble:
        name = "test-detector"

        def __init__(self, box):
            self.box = box
            self.loaded = False

        def isAvailable(self):
            return True

        def loadModel(self):
            self.loaded = True

        def detect(self, frame):
            x, y, w, h = self.box
            return [((x, y, w, h), frame[y:y + h, x:x + w])]

    def test_a_detector_crop_is_one_message(self) -> None:
        scene = _scene()
        detector = self._OneBubble((700, 100, 520, 140))
        received = []
        texts = self._run(self._pipeline(received, detector=detector), scene, received, expected_count=1)
        self.assertTrue(detector.loaded)
        self.assertEqual(texts, ["Hello there!\nHow are you?"])

    def test_an_unavailable_detector_falls_back_to_the_region(self) -> None:
        detector = self._OneBubble((0, 0, 1, 1))
        detector.isAvailable = lambda: False
        received = []
        pipeline = self._pipeline(received, detector=detector)
        self._run(pipeline, _scene(), received, expected_count=2)
        self.assertIsInstance(pipeline._detector, RegionCandidates)


class TestStartReasons(unittest.TestCase):
    def _start(self, probe=CAPTURE_OK, model_root=None, resolve=True):
        pipeline = OcrPipeline(callback=lambda payload: None, model_root=model_root,
                               capture_probe=lambda title: probe)
        patches = [patch.object(ocr_pipeline.ocr_engine, "isAvailable", return_value=True),
                   patch.object(ocr_pipeline.ocr_engine, "getReader", return_value=object())]
        if resolve:
            patches.append(patch.object(ocr_pipeline, "resolveModelFiles", return_value="files"))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaises(OcrStartError) as ctx:
            pipeline.start()
        self.assertIsNone(pipeline._thread)
        return ctx.exception.error_code

    def test_models_not_downloaded(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._start(model_root=root, resolve=False), ErrorCode.OCR_DISABLED_MODEL_MISSING)
        self.assertEqual(self._start(model_root=None, resolve=False), ErrorCode.OCR_DISABLED_MODEL_MISSING)

    def test_window_missing(self) -> None:
        self.assertEqual(self._start(probe=CAPTURE_WINDOW_NOT_FOUND), ErrorCode.OCR_DISABLED_WINDOW_NOT_FOUND)

    def test_no_capture_backend(self) -> None:
        self.assertEqual(self._start(probe=CAPTURE_UNAVAILABLE), ErrorCode.OCR_DISABLED_CAPTURE_UNAVAILABLE)


class TestApplyRegionAndFilter(unittest.TestCase):
    def test_settings_reach_the_running_pipeline(self) -> None:
        pipeline = OcrPipeline(callback=lambda payload: None)
        pipeline.applyConfig({"region": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}, "chatbox_filter": False})
        pipeline._applyPending()
        self.assertEqual(pipeline._region_source.region, (0.1, 0.2, 0.3, 0.4))
        self.assertFalse(pipeline._chatbox_filter)


MODEL_ROOT = os.environ.get("VRCT_OCR_MODEL_ROOT")


@unittest.skipUnless(MODEL_ROOT and Path(MODEL_ROOT).is_dir(), "opt-in: set VRCT_OCR_MODEL_ROOT to downloaded PP-OCR models")
class TestRealEngineWithoutDetector(unittest.TestCase):
    def test_reads_rendered_bubbles_with_downloaded_models(self) -> None:
        from models.ocr import ocr_engine_rapidocr as engine
        from models.ocr.ocr_languages import resolveModelSpec
        from models.ocr.ocr_models import resolveModelFiles

        spec = resolveModelSpec("auto")
        reader = engine.getReader(spec, resolveModelFiles(MODEL_ROOT, spec))
        self.assertIsNotNone(reader)
        received = []
        pipeline = OcrPipeline(callback=received.append, model_root=MODEL_ROOT, min_confidence=0.5)
        pipeline._reader = reader
        pipeline._capture = _FakeCapture(_scene().bgr())
        pipeline._tick()
        texts = [payload["text"] for payload in received]
        self.assertEqual(len(texts), 2, texts)
        self.assertTrue(any("こんにちは" in text for text in texts), texts)
        self.assertTrue(any("How are you" in text for text in texts), texts)
        self.assertFalse(any("WELCOME" in text for text in texts), texts)


if __name__ == "__main__":
    unittest.main()
