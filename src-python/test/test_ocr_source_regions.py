"""Per-surface regions and endpoint ordering; no native capture or inference."""

from threading import Event, Lock, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import controller as controller_module
import model as model_module
from config import config
from controller import Controller
from errors import ErrorCode
from models.ocr import ocr_capture, ocr_pipeline
from models.ocr.ocr_detection import FULL_REGION, normalizeRegion
from models.ocr.ocr_pipeline import OcrPipeline


WINDOW = {"x": 0.6, "y": 0.1, "width": 0.2, "height": 0.2}
VR = {"x": 0.1, "y": 0.5, "width": 0.3, "height": 0.4}
FULL = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}


@pytest.fixture
def captures(monkeypatch):
    window = Mock()
    window.capture.return_value = np.random.default_rng(1).integers(0, 255, (100, 200, 3), dtype=np.uint8)
    window.isAvailable.return_value = True
    vr = Mock()
    vr.capture.return_value = np.random.default_rng(2).integers(0, 255, (300, 300, 3), dtype=np.uint8)
    vr.isAvailable.return_value = True
    monkeypatch.setattr(ocr_capture, "_windowCapture", lambda _: ("hwnd", window))
    monkeypatch.setattr(ocr_capture, "OpenVRMirrorCapture", Mock(return_value=vr))
    monkeypatch.setattr(ocr_capture.sys, "platform", "win32")
    steamvr = Mock(return_value=False)
    monkeypatch.setattr(ocr_capture, "_isSteamvrRunning", steamvr)
    capture = ocr_capture.OcrCapture()
    yield capture, window, vr, steamvr
    capture.close()


@pytest.mark.parametrize("vr_region", [None, VR])
@pytest.mark.parametrize("detector_enabled", [False, True])
def test_frame_source_selects_its_own_region_and_fallback_restores_window(captures, monkeypatch, vr_region, detector_enabled):
    capture, window, vr, steamvr = captures
    pipeline = OcrPipeline(callback=Mock(), chatbox_filter=False)
    pipeline._capture = capture
    # Exercise actual cropping/filtering with synthetic frames and a fake reader.
    reads = []
    pipeline._reader = object()
    monkeypatch.setattr(ocr_pipeline.ocr_engine, "readtext_bgr_or_raise",
                        lambda reader, crop, confidence: reads.append(crop.shape) or [])
    regions = {"window": WINDOW}
    if vr_region is not None:
        regions["vr"] = vr_region
    pipeline.applyConfig({"regions": regions})
    pipeline._applyPending()
    if detector_enabled:
        detector = Mock(splits_bubbles=False, name="fake", model_path="fake")
        # Top-left and bottom-right bubbles both lie outside WINDOW and VR.
        detector.detect.side_effect = lambda frame: [
            ((0, 0, 10, 10), frame[:10, :10]),
            ((frame.shape[1] - 10, frame.shape[0] - 10, 10, 10), frame[-10:, -10:]),
        ]
        pipeline._detector = detector

    pipeline._tick()
    assert capture.source == "window"
    assert pipeline._region_source.region == normalizeRegion(WINDOW)
    assert reads == ([] if detector_enabled else [(20, 40, 3)])
    reads.clear()
    steamvr.return_value = True
    capture._selectBackend(force=True)
    pipeline._tick()
    assert capture.source == "vr"
    assert pipeline._region_source.region == (FULL_REGION if vr_region is None else normalizeRegion(VR))
    expected = ([(10, 10, 3)] * 2 if vr_region is None else []) if detector_enabled else [
        (300, 300, 3) if vr_region is None else (120, 90, 3)]
    assert reads == expected
    reads.clear()

    # Same get() call falls back from the HMD to the desktop window.
    vr.capture.return_value = None
    pipeline._tick()
    assert capture.source == "window"
    assert pipeline._region_source.region == normalizeRegion(WINDOW)
    assert reads == ([] if detector_enabled else [(20, 40, 3)])
    window.capture.return_value = None
    pipeline._tick()
    assert capture.source is None


def test_where_the_headset_view_cannot_be_read_it_is_never_attempted(captures, monkeypatch):
    # For example Linux without the OpenGL libraries the reader needs.
    capture, _, vr, steamvr = captures
    monkeypatch.setattr(ocr_capture.sys, "platform", "linux")
    vr.isAvailable.return_value = False
    steamvr.return_value = True
    assert ocr_capture.availableCaptureSources() == ["window"]
    assert capture.get() is not None
    assert capture.source == "window"
    vr.capture.assert_not_called()


def test_linux_reads_the_headset_view_when_it_can(captures, monkeypatch):
    capture, _, vr, steamvr = captures
    monkeypatch.setattr(ocr_capture.sys, "platform", "linux")
    steamvr.return_value = True
    assert ocr_capture.availableCaptureSources() == ["window", "vr"]
    capture._selectBackend(force=True)
    assert capture.get() is not None
    assert capture.source == "vr"


def test_pending_regions_follow_replaced_capture_and_legacy_region_only_edits_window():
    pipeline = OcrPipeline(callback=Mock())
    pipeline._capture = SimpleNamespace(source="window")
    pipeline.applyConfig({"regions": {"window": WINDOW, "vr": VR}})
    pipeline._applyPending()
    pipeline.applyConfig({"region": FULL})
    pipeline._applyPending()
    assert pipeline._region_source.region == FULL_REGION
    pipeline._capture = SimpleNamespace(source="vr")
    assert pipeline._region_source.region == normalizeRegion(VR)


@pytest.fixture
def subject(monkeypatch):
    backend = object.__new__(model_module.Model)
    backend._ocr_lifecycle_lock = Lock()
    backend._ocr_shutdown_requested = False
    backend.ensure_initialized = Mock()
    backend._ocrChatboxDetector = Mock(return_value=None)
    backend._ocr_detector_path = None
    backend.ocr_pipeline = OcrPipeline(callback=Mock())
    backend.ocr_pipeline._capture = SimpleNamespace(source="window")
    backend.ocr_pipeline._thread = Mock(is_alive=Mock(return_value=True))
    monkeypatch.setattr(controller_module, "model", backend)
    for key, value in {"OCR_CAPTURE_REGION": FULL, "OCR_VR_CAPTURE_REGION": FULL,
                       "OCR_MIN_CONFIDENCE": 0.85, "OCR_USE_CHATBOX_DETECTOR": True,
                       "ENABLE_OCR_CAPTURE": True}.items():
        monkeypatch.setattr(config, key, value)
    return Controller.__new__(Controller), backend


@pytest.mark.parametrize("source", ["window", "vr"])
def test_overlapping_endpoint_snapshots_cannot_restore_old_wider_region(subject, source):
    controller, backend = subject
    captured, release, newer_saved = Event(), Event(), Event()
    replies = []
    failures = []
    update = backend.updateOCRCaptureSettings
    count = 0

    def detector():
        nonlocal count
        count += 1
        if count == 1:
            captured.set()  # The first snapshot has already read the full region.
            assert release.wait(5)
        return None

    backend._ocrChatboxDetector.side_effect = detector
    setter = controller.setOcrCaptureRegion if source == "window" else controller.setOcrVrCaptureRegion

    def call(fn, *args):
        try:
            replies.append(fn(*args))
        except BaseException as exc:
            failures.append(exc)

    older = Thread(target=call, args=(controller.setOcrMinConfidence, 0.7))
    older.start()
    try:
        assert captured.wait(5)
        assert backend._ocr_lifecycle_lock.locked()

        def after_save():
            newer_saved.set()
            update()

        backend.updateOCRCaptureSettings = after_save
        newer = Thread(target=call, args=(setter, WINDOW))
        newer.start()
        try:
            assert newer_saved.wait(5)
            key = "OCR_CAPTURE_REGION" if source == "window" else "OCR_VR_CAPTURE_REGION"
            assert getattr(config, key) == WINDOW
        finally:
            release.set()
            newer.join(5)
        assert not newer.is_alive()
    finally:
        release.set()
        older.join(5)
    assert not older.is_alive()
    assert not failures
    assert len(replies) == 2 and all(reply["status"] == 200 for reply in replies)
    worker = backend.ocr_pipeline
    worker._applyPending()
    worker._capture.source = source
    assert getattr(config, key) == WINDOW
    assert worker._region_source.region == normalizeRegion(WINDOW)
    assert worker._min_confidence == 0.7


def test_detector_selection_is_in_the_same_transaction(subject):
    controller, backend = subject
    selected, release, disabled = Event(), Event(), Event()
    detector = Mock(name="fake", model_path="consented-detector")
    detector.isAvailable.return_value = True
    failures = []

    def build():
        if not config.OCR_USE_CHATBOX_DETECTOR:
            return None
        selected.set()
        assert release.wait(5)
        return detector

    backend._ocrChatboxDetector.side_effect = build
    original_update = backend.updateOCRCaptureSettings

    def call(fn, *args):
        try:
            assert fn(*args)["status"] == 200
        except BaseException as exc:
            failures.append(exc)

    older = Thread(target=call, args=(controller.setOcrMinConfidence, 0.7))
    older.start()
    try:
        assert selected.wait(5)
        assert backend._ocr_lifecycle_lock.locked()

        def after_save():
            disabled.set()
            original_update()

        backend.updateOCRCaptureSettings = after_save
        newer = Thread(target=call, args=(controller.setDisableOcrUseChatboxDetector,))
        newer.start()
        try:
            assert disabled.wait(5)
            assert not config.OCR_USE_CHATBOX_DETECTOR
        finally:
            release.set()
            newer.join(5)
        assert not newer.is_alive()
    finally:
        release.set()
        older.join(5)
    assert not older.is_alive() and not failures
    backend.ocr_pipeline._applyPending()
    assert backend.ocr_pipeline.detectorName == "region"
    assert backend._ocr_detector_path is None


def test_status_reports_worker_source_without_probing(subject, monkeypatch):
    controller, backend = subject
    monkeypatch.setattr(ocr_capture.sys, "platform", "win32")
    reader = Mock()
    reader.isAvailable.return_value = True
    monkeypatch.setattr(ocr_capture, "OpenVRMirrorCapture", Mock(return_value=reader))
    probe = Mock(side_effect=AssertionError("no capture probe"))
    monkeypatch.setattr(ocr_capture, "probeCapture", probe)
    pipeline = backend.ocr_pipeline
    pipeline._capture.get = Mock(side_effect=AssertionError("no frame capture"))
    for state, stage, error in (("waiting", "capture", None), ("reading", None, None),
                                ("retrying", "detector", ErrorCode.OCR_DISABLED_MODEL_LOAD_FAILED)):
        pipeline._runtimeState(state, stage, error)
        for source in ("window", "vr", None):
            pipeline._capture.source = source
            assert controller.getOcrCaptureStatus() == {"status": 200, "result": {
                "active": True, "source": source, "shared_window": None, "available_sources": ["window", "vr"],
                "state": state, "stage": stage, "error_code": error.value if error else None,
                "detector": "region"}}
    # A pending detector is not yet the detector actually used by the worker.
    detector = SimpleNamespace(name="vrct-vox-chatbox", isAvailable=lambda: True, loadModel=lambda: None)
    pipeline.applyConfig({"detector": detector})
    assert controller.getOcrCaptureStatus()["result"]["detector"] == "region"
    pipeline._applyPending()
    pipeline._runtimeState("reading")
    assert controller.getOcrCaptureStatus()["result"]["detector"] == "vrct-vox-chatbox"
    config.ENABLE_OCR_CAPTURE = False
    stopped = {"active": False, "source": None, "shared_window": None, "available_sources": ["window", "vr"],
               "state": "stopped", "stage": None, "error_code": None, "detector": None}
    assert controller.getOcrCaptureStatus()["result"] == stopped
    config.ENABLE_OCR_CAPTURE = True
    pipeline.requestShutdown()
    assert controller.getOcrCaptureStatus()["result"] == stopped
    backend.ocr_pipeline = None
    reader.isAvailable.return_value = False  # The headset view cannot be read on this system.
    assert controller.getOcrCaptureStatus()["result"] == {**stopped, "available_sources": ["window"]}
    pipeline._capture.get.assert_not_called()
    probe.assert_not_called()


def test_vr_endpoint_validates_and_preserves_window(subject):
    controller, backend = subject
    assert controller.setOcrVrCaptureRegion(VR) == {"status": 200, "result": VR}
    assert controller.getOcrVrCaptureRegion()["result"] == VR
    assert config.OCR_CAPTURE_REGION == FULL
    backend.ocr_pipeline._applyPending()
    for invalid in ({}, {**VR, "width": 2}, {**VR, "x": True}, {**VR, "height": float("nan")}):
        assert controller.setOcrVrCaptureRegion(invalid)["status"] == 400
        assert config.OCR_VR_CAPTURE_REGION == VR
        assert not backend.ocr_pipeline._pending


def test_start_queues_both_regions_before_worker_start(subject, monkeypatch):
    _, backend = subject
    backend.ocr_pipeline = None
    config.OCR_CAPTURE_REGION = WINDOW
    config.OCR_VR_CAPTURE_REGION = VR
    monkeypatch.setattr(config, "OCR_SOURCE_LANGUAGE", "auto")

    def fake_start(pipeline):
        assert pipeline._pending["regions"] == {"window": WINDOW, "vr": VR}
        pipeline._capture = SimpleNamespace(source="vr")
        pipeline._applyPending()
        assert pipeline._region_source.region == normalizeRegion(VR)
        return True

    monkeypatch.setattr(OcrPipeline, "start", fake_start)
    assert backend.startOCRCapture(Mock())
