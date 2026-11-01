"""VRCT-VOX's own chatbox detector: path selection, the upstream-model guard, region and filter.

Everything runs on a fake ONNX file (bytes whose hash a patched catalog entry
expects) and a fake onnxruntime session, except the opt-in test at the end:
set VRCT_CHATBOX_DETECTOR to the trained vrct_vox_chatbox_yolox_tiny.onnx
(VRCT_CHATBOX_FRAMES defaults to ~/.cache/vrct-vox-chatbox-lab/dataset/raw;
set VRCT_OCR_MODEL_ROOT as well to read the detected chatboxes with PP-OCR).
"""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from config import config
import model as model_module
from models.model_downloads.catalog import CATALOG, DETECTOR_FILE_NAME, DETECTOR_MODEL_ID, DETECTOR_SHA256, DETECTOR_SIZE
from models.ocr import ocr_bubble_detector, ocr_chatbox_detector, ocr_models, ocr_pipeline
from models.ocr.ocr_capture import CAPTURE_OK
from models.ocr.ocr_chatbox_detector import ChatboxDetector, buildChatboxDetector, isAllowedModelPath
from models.ocr.ocr_detection import RegionCandidates
from models.ocr.ocr_pipeline import OcrPipeline
from ocr_synthetic import Scene, shifted

FAKE_ONNX = b"not really an onnx graph, but the catalog says these are the bytes"


def _scene():
    scene = Scene()
    scene.bubble(360, 120, ["こんにちは、元気ですか？", "今日はどこ行く？"])
    scene.bubble(960, 140, ["Hello there!", "How are you?"])
    scene.sign(420, 560, "WELCOME TO THE CLUB")
    return scene


# Boxes around what _scene() draws, in frame pixels (x, y, w, h).
JAPANESE_BOX, ENGLISH_BOX, SIGN_BOX = (180, 100, 360, 100), (820, 120, 280, 100), (400, 545, 380, 60)


class _FakeSession:
    """onnxruntime stand-in: returns the scene's boxes in YOLOX's raw layout."""

    def __init__(self, boxes):
        self.boxes = boxes
        self.calls = 0

    def get_inputs(self):
        return [type("Input", (), {"name": "images"})()]

    def run(self, _outputs, feeds):
        self.calls += 1
        tensor = feeds["images"]
        # Letterbox scale: the long side of the 1280x720 scene maps to image_size (1280).
        scale = 1.0
        assert tensor.shape[1] == 3
        rows = [[(x + w / 2) * scale, (y + h / 2) * scale, w * scale, h * scale, 0.95, 0.99]
                for x, y, w, h in self.boxes]
        rows.append([10, 10, 5, 5, 0.1, 0.1])  # below the confidence threshold
        return [np.asarray([rows], dtype=np.float32)]


class _FakeCapture:
    def __init__(self, frame):
        self.frame = frame
        self.closed = False

    def get(self):
        return self.frame

    def close(self):
        self.closed = True


def _fake_ocr(scene):
    """readtext_bgr stand-in: the scene's lines inside the crop (crops are located by template match)."""
    import cv2
    frame = scene.bgr()

    def read(reader, crop, min_confidence):
        patch_ = crop[:24, :24]
        _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(frame, patch_, cv2.TM_CCOEFF_NORMED))
        if score < 0.99 or not np.array_equal(frame[dy:dy + crop.shape[0], dx:dx + crop.shape[1]], crop):
            return []
        inside = [line for line in scene.lines
                  if line["left"] >= dx and line["right"] <= dx + crop.shape[1]
                  and line["top"] >= dy and line["bottom"] <= dy + crop.shape[0]]
        return shifted(inside, dx, dy)
    return read


class _DownloadRoot(unittest.TestCase):
    """A downloaded_models root holding a fake detector the patched catalog accepts."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="vrct-detector-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        entry = ocr_models.catalogEntry(DETECTOR_MODEL_ID)
        artifact = replace(entry.artifacts[0], size=len(FAKE_ONNX), sha256=hashlib.sha256(FAKE_ONNX).hexdigest())
        self.entry = replace(entry, artifacts=(artifact,))
        entries = patch.dict(ocr_models._ENTRIES, {DETECTOR_MODEL_ID: self.entry})
        entries.start()
        self.addCleanup(entries.stop)
        ocr_models._verified.clear()
        self.addCleanup(ocr_models._verified.clear)
        self.path = self.root / self.entry.id / self.entry.revision / DETECTOR_FILE_NAME

    def install(self, data: bytes = FAKE_ONNX) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(data)
        return self.path


class TestVerifiedDownloadOnly(_DownloadRoot):
    def test_verified_download_builds_our_detector(self) -> None:
        self.install()
        detector = buildChatboxDetector(self.root)
        self.assertIsInstance(detector, ChatboxDetector)
        self.assertEqual(detector.model_path, str(self.path))
        self.assertTrue(ocr_chatbox_detector.isDetectorInstalled(self.root))

    def test_missing_download_means_no_detector(self) -> None:
        self.assertIsNone(buildChatboxDetector(self.root))
        self.assertIsNone(buildChatboxDetector(None))
        self.assertFalse(ocr_chatbox_detector.isDetectorInstalled(self.root))

    def test_changed_file_is_not_loaded(self) -> None:
        self.install(bytes(reversed(FAKE_ONNX)))  # same size, other hash
        with patch.object(ocr_chatbox_detector, "errorLogging"):
            self.assertIsNone(buildChatboxDetector(self.root))

    def test_symlinked_file_is_not_loaded(self) -> None:
        target = self.root / "elsewhere.onnx"
        target.write_bytes(FAKE_ONNX)
        self.path.parent.mkdir(parents=True)
        try:
            self.path.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertIsNone(buildChatboxDetector(self.root))


class TestUpstreamModelNeverLoads(unittest.TestCase):
    def test_file_names_differ(self) -> None:
        self.assertEqual(DETECTOR_FILE_NAME, "vrct_vox_chatbox_yolox_tiny.onnx")
        self.assertNotEqual(DETECTOR_FILE_NAME.lower(), ocr_bubble_detector.MODEL_FILE_NAME.lower())

    def test_only_our_file_name_outside_the_bundled_directory_is_allowed(self) -> None:
        bundled = Path(ocr_bubble_detector.__file__).resolve().parent / "onnx"
        for path in (None, "", "model.onnx", "chatbox_yolox_tiny.onnx", "/x/chatbox_yolox_tiny.onnx",
                     str(bundled / "chatbox_yolox_tiny.onnx"), str(bundled / DETECTOR_FILE_NAME),
                     "/x/VRCT_VOX_CHATBOX_YOLOX_TINY.onnx"):
            self.assertFalse(isAllowedModelPath(path), path)
            with self.assertRaises(ValueError):
                ChatboxDetector(path)
        self.assertTrue(isAllowedModelPath(f"/data/downloaded_models/{DETECTOR_MODEL_ID}/rev/{DETECTOR_FILE_NAME}"))

    def test_find_model_path_is_never_consulted(self) -> None:
        self.assertNotIn("findModelPath", vars(ocr_chatbox_detector))
        with patch.object(ocr_bubble_detector, "findModelPath", side_effect=AssertionError("upstream lookup")):
            detector = ChatboxDetector(f"/nowhere/{DETECTOR_FILE_NAME}")
            self.assertFalse(detector.isAvailable())
            self.assertEqual(detector.detect(np.zeros((8, 8, 3), np.uint8)), [])

    def test_pipeline_module_does_not_import_the_upstream_detector(self) -> None:
        self.assertNotIn("BubbleDetector", vars(ocr_pipeline))
        self.assertNotIn("ocr_chatbox_detector", vars(ocr_pipeline))


class _ModelHarness(_DownloadRoot):
    """model.startOCRCapture with OcrPipeline replaced by a recorder."""

    def setUp(self) -> None:
        super().setUp()
        self.created = []
        created = self.created

        class Recorder:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.applied = []
                created.append(self)

            def start(self):
                return True

            def applyConfig(self, settings):
                self.applied.append(settings)

        self.Recorder = Recorder
        p = patch.object(model_module, "OcrPipeline", Recorder)
        p.start()
        self.addCleanup(p.stop)
        for name in ("OCR_USE_CHATBOX_DETECTOR", "OCR_SOURCE_LANGUAGE"):
            self.addCleanup(setattr, config, name, getattr(config, name))
        config.OCR_SOURCE_LANGUAGE = "auto"
        self.model = object.__new__(model_module.Model)
        self.model._inited = True
        self.model.ocr_pipeline = None
        self.model._ocr_model_root = None
        self.model._ocr_detector_path = None

    def start(self):
        self.assertTrue(self.model.startOCRCapture(lambda payload: None, model_root=self.root))
        return self.created[-1].kwargs["detector"]


class TestPathSelection(_ModelHarness):
    def test_installed_and_switched_on_uses_the_detector(self) -> None:
        self.install()
        config.OCR_USE_CHATBOX_DETECTOR = True
        detector = self.start()
        self.assertIsInstance(detector, ChatboxDetector)
        self.assertEqual(detector.model_path, str(self.path))

    def test_switched_off_reads_without_a_detector(self) -> None:
        self.install()
        config.OCR_USE_CHATBOX_DETECTOR = False
        self.assertIsNone(self.start())

    def test_not_downloaded_reads_without_a_detector(self) -> None:
        config.OCR_USE_CHATBOX_DETECTOR = True
        self.assertIsNone(self.start())

    def test_unverified_download_reads_without_a_detector(self) -> None:
        self.install(b"x" * len(FAKE_ONNX))
        config.OCR_USE_CHATBOX_DETECTOR = True
        with patch.object(ocr_chatbox_detector, "errorLogging"):
            self.assertIsNone(self.start())

    def test_switch_reaches_the_running_pipeline_only_when_it_changes(self) -> None:
        self.install()
        config.OCR_USE_CHATBOX_DETECTOR = True
        self.start()
        pipeline = self.created[-1]
        self.model.updateOCRCaptureSettings()
        self.assertNotIn("detector", pipeline.applied[-1])  # unchanged: nothing to swap
        config.OCR_USE_CHATBOX_DETECTOR = False
        self.model.updateOCRCaptureSettings()
        self.assertIsNone(pipeline.applied[-1]["detector"])
        config.OCR_USE_CHATBOX_DETECTOR = True
        self.model.updateOCRCaptureSettings()
        self.assertIsInstance(pipeline.applied[-1]["detector"], ChatboxDetector)


class _PipelineHarness(_DownloadRoot):
    """The real pipeline and BubbleDetector decode on a fake onnxruntime session."""

    def detector(self, boxes):
        self.install()
        detector = buildChatboxDetector(self.root)
        self.session = _FakeSession(boxes)
        fake_ort = type("FakeOrt", (), {
            "SessionOptions": staticmethod(lambda: type("Options", (), {})()),
            "InferenceSession": staticmethod(lambda path, options, providers: self.session),
        })
        p = patch.object(ocr_bubble_detector, "ort", fake_ort)
        p.start()
        self.addCleanup(p.stop)
        return detector

    def read(self, scene, expected_count, **kwargs):
        received = []
        pipeline = OcrPipeline(callback=received.append, source_language="auto", poll_interval_ms=100,
                               min_confidence=0.5, capture_probe=lambda title: CAPTURE_OK, **kwargs)
        capture = _FakeCapture(scene.bgr())
        for p in (patch.object(ocr_pipeline, "resolveModelFiles", return_value="files"),
                  patch.object(ocr_pipeline.ocr_engine, "isAvailable", return_value=True),
                  patch.object(ocr_pipeline.ocr_engine, "getReader", return_value=object()),
                  patch.object(ocr_pipeline.ocr_engine, "readtext_bgr", side_effect=_fake_ocr(scene)),
                  patch.object(ocr_pipeline, "OcrCapture", return_value=capture)):
            p.start()
            self.addCleanup(p.stop)
        self.assertTrue(pipeline.start())
        try:
            deadline = time.monotonic() + 5
            while len(received) < expected_count and time.monotonic() < deadline:
                time.sleep(0.02)
            time.sleep(0.25)
        finally:
            pipeline.stop()
        return pipeline, sorted(payload["text"] for payload in received)


class TestPipelineWithDetector(_PipelineHarness):
    def test_each_detected_chatbox_is_one_message(self) -> None:
        detector = self.detector([JAPANESE_BOX, ENGLISH_BOX])
        pipeline, texts = self.read(_scene(), 2, detector=detector)
        self.assertEqual(pipeline.detectorName, "vrct-vox-chatbox")
        self.assertEqual(texts, sorted(["こんにちは、元気ですか？\n今日はどこ行く？", "Hello there!\nHow are you?"]))
        self.assertGreater(self.session.calls, 0)

    def test_region_keeps_detections_whose_centre_is_inside(self) -> None:
        detector = self.detector([JAPANESE_BOX, ENGLISH_BOX])
        # Right half: only the English chatbox's centre (960, 170) is inside.
        _, texts = self.read(_scene(), 1, detector=detector, region={"x": 0.5, "y": 0.0, "width": 0.5, "height": 0.5})
        self.assertEqual(texts, ["Hello there!\nHow are you?"])

    def test_chatbox_filter_drops_world_text_the_detector_proposed(self) -> None:
        detector = self.detector([ENGLISH_BOX, SIGN_BOX])
        _, texts = self.read(_scene(), 1, detector=detector)
        self.assertEqual(texts, ["Hello there!\nHow are you?"])

    def test_chatbox_filter_off_reads_every_detection(self) -> None:
        detector = self.detector([ENGLISH_BOX, SIGN_BOX])
        _, texts = self.read(_scene(), 2, detector=detector, chatbox_filter=False)
        self.assertEqual(texts, ["Hello there!\nHow are you?", "WELCOME TO THE CLUB"])


class TestLiveSwitch(unittest.TestCase):
    class _Fake:
        name = "fake-detector"
        splits_bubbles = False

        def __init__(self, available=True, load_error=None):
            self.available, self.load_error, self.loaded = available, load_error, False

        def isAvailable(self):
            return self.available

        def loadModel(self):
            if self.load_error:
                raise self.load_error
            self.loaded = True

        def detect(self, frame):
            return []

    def _switch(self, detector, pipeline=None):
        pipeline = pipeline or OcrPipeline(callback=lambda payload: None)
        pipeline.applyConfig({"detector": detector})
        with patch.object(ocr_pipeline, "errorLogging"):
            pipeline._applyPending()
        return pipeline

    def test_detector_on_and_off_while_running(self) -> None:
        fake = self._Fake()
        pipeline = self._switch(fake)
        self.assertIs(pipeline._detector, fake)
        self.assertTrue(fake.loaded)
        self._switch(None, pipeline)
        self.assertIsInstance(pipeline._detector, RegionCandidates)
        self.assertEqual(pipeline.detectorName, "region")

    def test_broken_or_unavailable_detector_keeps_reading_the_region(self) -> None:
        for fake in (self._Fake(available=False), self._Fake(load_error=RuntimeError("bad onnx"))):
            self.assertIsInstance(self._switch(fake)._detector, RegionCandidates)


DETECTOR_MODEL = os.environ.get("VRCT_CHATBOX_DETECTOR")
FRAMES = Path(os.environ.get("VRCT_CHATBOX_FRAMES") or Path.home() / ".cache/vrct-vox-chatbox-lab/dataset/raw")
OCR_ROOT = os.environ.get("VRCT_OCR_MODEL_ROOT")


def _labelled_frames(limit):
    """(frame path, [label boxes (x0, y0, x1, y1)], sent text) from the lab's YOLO labels."""
    out = []
    for session in sorted(FRAMES.glob("*/labels")):
        texts = {}
        labels_jsonl = session.parent / "labels.jsonl"
        if labels_jsonl.is_file():
            for line in labels_jsonl.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                texts[row["file"]] = (row.get("read"), row.get("score"))
        for label in sorted(session.glob("*.txt")):
            frame = session.parent / (label.stem + ".png")
            rows = [r.split() for r in label.read_text().splitlines() if r.strip()]
            if frame.is_file() and rows:
                out.append((frame, rows, texts.get(frame.name, (None, None))))
    step = max(1, len(out) // limit)
    return out[::step][:limit]


@unittest.skipUnless(DETECTOR_MODEL and Path(DETECTOR_MODEL).is_file(),
                     "opt-in: set VRCT_CHATBOX_DETECTOR to vrct_vox_chatbox_yolox_tiny.onnx")
class TestRealModel(unittest.TestCase):
    """The trained model through the same download layout, hash check and pipeline the app uses."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="vrct-detector-real-"))
        entry = ocr_models.catalogEntry(DETECTOR_MODEL_ID)
        target = cls.root / entry.id / entry.revision / DETECTOR_FILE_NAME
        target.parent.mkdir(parents=True)
        shutil.copyfile(DETECTOR_MODEL, target)
        cls.frames = _labelled_frames(40)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_file_matches_the_catalog_pins(self) -> None:
        data = Path(DETECTOR_MODEL).read_bytes()
        self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (DETECTOR_SIZE, DETECTOR_SHA256))

    def test_detects_labelled_chatboxes(self) -> None:
        import cv2
        if not self.frames:
            self.skipTest(f"no labelled frames under {FRAMES}")
        detector = buildChatboxDetector(self.root)
        self.assertIsInstance(detector, ChatboxDetector)
        detector.loadModel()
        found = total = extra = 0
        for frame_path, rows, _ in self.frames:
            frame = cv2.imread(str(frame_path))
            height, width = frame.shape[:2]
            boxes = [bbox for bbox, _ in detector.detect(frame)]
            matched = set()
            for _, cx, cy, _, _ in rows:
                total += 1
                px, py = float(cx) * width, float(cy) * height
                hits = [i for i, (x, y, w, h) in enumerate(boxes) if x <= px <= x + w and y <= py <= y + h]
                found += bool(hits)
                matched.update(hits)
            extra += len(boxes) - len(matched)
        print(f"real detector: {found}/{total} labelled chatboxes, {extra} extra, {len(self.frames)} frames")
        self.assertGreaterEqual(found / total, 0.9)
        self.assertLessEqual(extra, max(2, total // 10))

    @unittest.skipUnless(OCR_ROOT and Path(OCR_ROOT).is_dir(), "set VRCT_OCR_MODEL_ROOT to read the chatboxes too")
    def test_pipeline_reads_what_was_sent(self) -> None:
        import cv2
        from models.ocr import ocr_engine_rapidocr as engine
        from models.ocr.ocr_languages import resolveModelSpec
        frames = [f for f in self.frames if f[2][0] and f[2][1] == 1.0][:12]
        if not frames:
            self.skipTest("no frames with a confirmed reading")
        spec = resolveModelSpec("auto")
        reader = engine.getReader(spec, ocr_models.resolveModelFiles(OCR_ROOT, spec))
        detector = buildChatboxDetector(self.root)
        detector.loadModel()
        matches = 0
        for frame_path, _, (expected, _) in frames:
            received = []
            pipeline = OcrPipeline(callback=received.append, source_language="auto", detector=detector)
            pipeline._reader = reader
            pipeline._capture = _FakeCapture(cv2.imread(str(frame_path)))
            pipeline._tick()
            squash = lambda text: "".join(text.split())
            matches += any(squash(p["text"]) == squash(expected) for p in received)
        print(f"real detector + PP-OCR: {matches}/{len(frames)} chatboxes read as sent")
        self.assertGreaterEqual(matches / len(frames), 0.75)


if __name__ == "__main__":
    unittest.main()
