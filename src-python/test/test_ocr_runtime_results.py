"""Pipeline runtime failures, activation and status with fakes only."""

import ctypes
from threading import Event, RLock, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from models.ocr import ocr_bubble_detector, ocr_capture, ocr_capture_hwnd, ocr_capture_openvr, ocr_capture_x11, ocr_pipeline


@pytest.fixture
def subject(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(ocr_pipeline.time, "monotonic", lambda: clock.now)
    logs, traces, messages = [], [], []
    monkeypatch.setattr(ocr_pipeline, "printLog", logs.append)
    monkeypatch.setattr(ocr_pipeline, "errorLogging", lambda: traces.append("trace"))
    frame = np.zeros((8, 8, 3), np.uint8)
    capture = SimpleNamespace(get=Mock(return_value=frame), backend="x11", close=Mock())
    pipeline = ocr_pipeline.OcrPipeline(messages.append, chatbox_filter=False)
    pipeline._capture = capture
    pipeline._reader = Mock(return_value=SimpleNamespace(txts=[], scores=[], boxes=None))
    return SimpleNamespace(clock=clock, pipeline=pipeline, capture=capture, frame=frame,
                           logs=logs, traces=traces, messages=messages)


def test_detector_run_failure_backs_off_logs_once_and_recovers(subject, monkeypatch):
    s = subject
    detector = ocr_bubble_detector.BubbleDetector(model_path=__file__)
    session = Mock()
    session.run.side_effect = RuntimeError("broken detector")
    monkeypatch.setattr(detector, "isAvailable", lambda: True)
    monkeypatch.setattr(detector, "loadModel", lambda: session)
    monkeypatch.setattr(detector, "_letterbox", lambda frame: (frame, 1))
    s.pipeline._detector = detector
    for at, delay in ((100, 1), (101, 2), (103, 4), (107, 8)):
        s.clock.now = at
        s.pipeline._tick()
        status = s.pipeline.runtimeStatus
        assert status["state"] == "retrying"
        assert status["stage"] == "detector"
        assert status["error_code"] == "OCR_DISABLED_MODEL_LOAD_FAILED"
        retry = s.pipeline._stage_retries["detector"]
        assert retry.retry_at == at + delay
        calls = session.run.call_count
        s.clock.now = retry.retry_at - 0.01
        s.pipeline._tick()
        assert session.run.call_count == calls
    assert len(s.traces) == 1
    s.pipeline._reader.assert_not_called()  # No silent fallback to wider region OCR.
    s.clock.now = 115
    session.run.side_effect = None
    session.run.return_value = [np.empty((1, 0, 6))]
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "reading"
    assert retry.retry_at == 0
    assert sum("recovered" in log for log in s.logs) == 1
    assert s.pipeline._engine_failure_count == 0


def test_detector_exposes_distinct_failure_instead_of_empty_candidates(monkeypatch):
    detector = ocr_bubble_detector.BubbleDetector(model_path=__file__)
    monkeypatch.setattr(detector, "isAvailable", lambda: True)
    monkeypatch.setattr(detector, "loadModel", Mock(side_effect=RuntimeError("session failed")))
    with pytest.raises(ocr_bubble_detector.OcrDetectorError, match="session failed"):
        detector.detect(np.zeros((8, 8, 3), np.uint8))


def test_capture_exceptions_back_off_and_missing_frames_do_not_claim_recovery(subject):
    s = subject
    s.capture.get.side_effect = RuntimeError("capture failed")
    for at, delay in ((100, 1), (101, 2), (103, 4), (107, 8), (115, 16), (131, 30), (161, 30)):
        s.clock.now = at
        s.pipeline._tick()
        assert s.pipeline._stage_retries["capture"].retry_at == at + delay
    assert len(s.traces) == 1
    s.clock.now = 190
    s.pipeline._tick()
    assert s.capture.get.call_count == 7
    s.clock.now = 191
    s.capture.get.side_effect = None
    s.capture.get.return_value = None
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "retrying"
    assert not any("recovered" in line for line in s.logs)
    s.capture.get.return_value = s.frame
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "reading"
    assert sum("recovered" in line for line in s.logs) == 1


def test_first_missing_frame_is_waiting_not_ready(subject):
    s = subject
    s.capture.get.return_value = None
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "waiting"
    s.capture.get.return_value = s.frame
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "reading"


@pytest.mark.parametrize("working_fallback", [False, True])
@pytest.mark.parametrize("failure_at", ["acquire", "read"])
def test_openvr_failure_retries_only_without_a_working_fallback(subject, monkeypatch, working_fallback, failure_at):
    s = subject
    mirror = SimpleNamespace(read=Mock(return_value=s.frame), close=Mock())
    session = SimpleNamespace(acquire=Mock(), release=Mock())
    vr = ocr_capture_openvr.OpenVRMirrorCapture()
    monkeypatch.setattr(vr, "isAvailable", lambda: True)
    monkeypatch.setattr(vr, "_isVrchatScene", lambda: True)
    monkeypatch.setattr(ocr_capture_openvr, "openvr_session", session)
    monkeypatch.setattr(ocr_capture_openvr, "openvr", SimpleNamespace(
        VRApplication_Background=2, Eye_Left=0, IVRCompositor=Mock()))
    monkeypatch.setattr(ocr_capture_openvr, "D3D11Mirror", lambda *args: mirror)
    monkeypatch.setattr(ocr_capture_openvr, "errorLogging", lambda: s.traces.append("vr trace"))
    monkeypatch.setattr(ocr_capture_openvr, "printLog", s.logs.append)
    failing = session.acquire if failure_at == "acquire" else mirror.read
    failing.side_effect = RuntimeError("device lost")
    window = SimpleNamespace(isAvailable=lambda: True, capture=Mock(
        return_value=s.frame if working_fallback else None), close=Mock())
    monkeypatch.setattr(ocr_capture, "_windowCapture", lambda title: ("hwnd", window))
    monkeypatch.setattr(ocr_capture, "OpenVRMirrorCapture", lambda: vr)
    monkeypatch.setattr(ocr_capture, "_isSteamvrRunning", lambda: True)
    monkeypatch.setattr(ocr_capture.sys, "platform", "win32")
    monkeypatch.setattr(ocr_capture, "isFrameBlank", lambda frame: frame is None)
    s.pipeline._capture = capture = ocr_capture.OcrCapture()
    for tick in range(80):
        s.clock.now = 100 + tick * 0.75
        s.pipeline._tick()
        assert s.pipeline.runtimeStatus["state"] == ("reading" if working_fallback else "retrying")
    assert len(s.traces) == 1
    retry = s.pipeline._stage_retries["capture"]
    if working_fallback:
        assert retry.retry_at == 0
        assert window.capture.call_count == 80
    else:
        assert s.pipeline.runtimeStatus["error_code"] == "OCR_DISABLED_CAPTURE_UNAVAILABLE"
        assert retry.delay == 30
        assert window.capture.call_count < 10
    if failure_at == "read":
        assert mirror.close.call_count == session.release.call_count == failing.call_count
    # A real VR frame (with nonuniform pixels) proves recovery.
    failing.side_effect = None
    s.frame[0, 0, 0] = 255
    s.clock.now = max(retry.retry_at, s.clock.now + 5)
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "reading"
    assert capture.source == "vr"
    assert retry.retry_at == 0


def test_hwnd_failed_read_backs_off_but_minimized_window_waits(subject, monkeypatch):
    s = subject
    window = ocr_capture_hwnd.HwndCapture()
    monkeypatch.setattr(window, "isAvailable", lambda: True)
    monkeypatch.setattr(ocr_capture_hwnd, "_find_vrchat_hwnd", lambda title: 42)
    monkeypatch.setattr(ocr_capture_hwnd, "_window_rect", lambda hwnd: (0, 0, 8, 8))
    iconic = Mock(return_value=True)
    monkeypatch.setattr(ocr_capture_hwnd, "_is_iconic", iconic)
    read = Mock(return_value=None)
    monkeypatch.setattr(ocr_capture_hwnd, "_print_window", read)
    monkeypatch.setattr(ocr_capture_hwnd, "errorLogging", lambda: s.traces.append("hwnd trace"))
    monkeypatch.setattr(ocr_capture_hwnd, "printLog", s.logs.append)
    monkeypatch.setattr(ocr_capture, "_windowCapture", lambda title: ("hwnd", window))
    monkeypatch.setattr(ocr_capture, "_isSteamvrRunning", lambda: False)
    monkeypatch.setattr(ocr_capture, "isFrameBlank", lambda frame: frame is None)
    s.pipeline._capture = ocr_capture.OcrCapture()
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "waiting"
    read.assert_not_called()
    iconic.return_value = False
    for at, delay in ((100, 1), (101, 2), (103, 4), (107, 8)):
        s.clock.now = at
        s.pipeline._tick()
        assert s.pipeline.runtimeStatus["error_code"] == "OCR_DISABLED_CAPTURE_UNAVAILABLE"
        assert s.pipeline._stage_retries["capture"].retry_at == at + delay
        s.clock.now += 0.5
        s.pipeline._tick()
    assert read.call_count == 4
    assert len(s.traces) == 1
    s.clock.now = 115
    read.return_value = s.frame
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "reading"
    assert s.pipeline._stage_retries["capture"].retry_at == 0


def test_unsupported_x11_format_reaches_pipeline_through_unchanged_facade(subject, monkeypatch):
    s = subject
    x11 = ocr_capture_x11.X11WindowCapture()
    monkeypatch.setattr(x11, "isAvailable", lambda: True)
    monkeypatch.setattr(x11, "_open", lambda: 1)
    monkeypatch.setattr(x11, "findWindow", lambda: 42)
    monkeypatch.setattr(x11, "_begin", lambda: None)
    monkeypatch.setattr(x11, "_failed", lambda: False)
    monkeypatch.setattr(x11, "_viewable", lambda window: SimpleNamespace(width=8, height=8))
    data = ctypes.create_string_buffer(bytes(8 * 8 * 4))
    image = ocr_capture_x11._XImage()
    image.width = image.height = 8
    image.bytes_per_line, image.bits_per_pixel = 32, 32
    image.red_mask, image.green_mask, image.blue_mask = 0x3FF00000, 0xFFC00, 0x3FF
    image.data = ctypes.cast(data, ctypes.c_void_p)
    destroyed = []
    image.f.destroy_image = ocr_capture_x11._DESTROY(lambda pointer: destroyed.append(True) or 0)
    lib = SimpleNamespace(XGetImage=Mock(return_value=ctypes.pointer(image)))
    monkeypatch.setattr(ocr_capture_x11._State, "lib", lib)
    monkeypatch.setattr(ocr_capture, "_windowCapture", lambda title: ("x11", x11))
    monkeypatch.setattr(ocr_capture, "_isSteamvrRunning", lambda: False)
    monkeypatch.setattr(ocr_capture, "errorLogging", lambda: s.traces.append("capture trace"))
    monkeypatch.setattr(ocr_capture, "printLog", s.logs.append)
    monkeypatch.setattr(ocr_capture, "isFrameBlank", lambda frame: frame is None)
    s.pipeline._capture = ocr_capture.OcrCapture()
    for at in (100, 100.75, 101, 102, 103):
        s.clock.now = at
        s.pipeline._tick()
    assert lib.XGetImage.call_count == 3
    assert len(destroyed) == 3  # Invalid images are still disposed.
    assert len(s.traces) == 1
    assert s.pipeline.runtimeStatus["error_code"] == "OCR_DISABLED_CAPTURE_UNAVAILABLE"
    assert s.pipeline.runtimeStatus["stage"] == "capture"
    image.red_mask, image.green_mask, image.blue_mask = 0xFF0000, 0xFF00, 0xFF
    s.clock.now = 107
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["state"] == "reading"
    assert len(destroyed) == 4
    assert sum("recovered" in log for log in s.logs) == 1


def test_status_reports_worker_detector_only_after_pending_swap(subject):
    s = subject
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["detector"] == "region"
    detector = SimpleNamespace(name="vrct-vox-chatbox", isAvailable=lambda: True,
                               loadModel=lambda: None, detect=lambda frame: [])
    s.pipeline.applyConfig({"detector": detector})
    assert s.pipeline.runtimeStatus["detector"] == "region"
    s.pipeline._applyPending()
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["detector"] == "vrct-vox-chatbox"
    detector.loadModel = Mock(side_effect=RuntimeError("load failed"))
    s.pipeline.applyConfig({"detector": detector})
    s.pipeline._applyPending()
    s.pipeline._tick()
    assert s.pipeline.runtimeStatus["detector"] == "region"
    s.pipeline.stop()
    assert s.pipeline.runtimeStatus["state"] == "stopped"


def test_replacing_failed_detector_clears_only_its_retry(subject):
    s = subject
    detector = SimpleNamespace(name="broken", detect=Mock(side_effect=RuntimeError("bad detector")))
    s.pipeline._detector = detector
    s.pipeline._tick()
    assert s.pipeline._stage_retries["detector"].retry_at > s.clock.now
    s.pipeline.applyConfig({"detector": None})
    s.pipeline._applyPending()
    s.pipeline._tick()  # No fake time advance: the new source is tried immediately.
    assert s.pipeline.runtimeStatus["state"] == "reading"
    assert s.pipeline.runtimeStatus["detector"] == "region"


def test_runtime_query_is_read_only_and_installation_does_not_imply_adoption(subject, monkeypatch):
    import controller as controller_module
    import model as model_module
    from config import config

    s = subject
    backend = object.__new__(model_module.Model)
    backend.ocr_pipeline = s.pipeline
    backend._ocrChatboxDetector = Mock()
    backend.updateOCRCaptureSettings = Mock()
    s.pipeline._thread = Mock()
    s.pipeline._thread.is_alive.return_value = True
    s.pipeline._tick()
    controller = controller_module.Controller.__new__(controller_module.Controller)
    monkeypatch.setattr(controller_module, "model", backend)
    monkeypatch.setattr(config, "ENABLE_OCR_CAPTURE", True)
    monkeypatch.setattr(config, "OCR_SOURCE_LANGUAGE", "auto")
    monkeypatch.setattr(config, "OCR_USE_CHATBOX_DETECTOR", True)
    probe = Mock(return_value="ok")
    monkeypatch.setattr(controller_module.ocr_capture, "probeCapture", probe)
    monkeypatch.setattr(controller_module.ocr_models, "missingModels", lambda root, spec: [])
    monkeypatch.setattr(controller_module.ocr_chatbox_detector, "isDetectorInstalled", lambda root: True)
    assert controller.getOcrCaptureStatus()["result"]["detector"] == "region"
    probe.assert_not_called()
    readiness = controller.getOcrReadiness()["result"]
    assert readiness["detector_installed"] and readiness["detector_enabled"]
    assert readiness["runtime"]["detector"] == "region"
    backend._ocrChatboxDetector.assert_not_called()
    backend.updateOCRCaptureSettings.assert_not_called()
    assert not s.pipeline._pending


def test_shutdown_cancels_activation_wait_without_capture_or_delivery(monkeypatch):
    waiting = Event()

    class StopEvent(Event):
        def wait(self, timeout=None):
            waiting.set()
            return super().wait(timeout)

    pipeline = ocr_pipeline.OcrPipeline(Mock(), activation_ready=lambda: False)
    pipeline._stop_event = StopEvent()
    capture = Mock()
    monkeypatch.setattr(ocr_pipeline, "OcrCapture", lambda **kwargs: capture)
    monkeypatch.setattr(ocr_pipeline, "lowerCurrentThread", lambda: None)
    worker = Thread(target=pipeline._run, daemon=True)
    pipeline._thread = worker
    worker.start()
    try:
        assert waiting.wait(1)
        pipeline.requestShutdown()
        assert pipeline.stop()
        assert not worker.is_alive()
        capture.get.assert_not_called()
        pipeline._callback.assert_not_called()
        capture.close.assert_called_once()
    finally:
        pipeline.requestShutdown()
        worker.join(1)


def test_first_tick_during_enable_waits_for_controller_commit(monkeypatch):
    import controller as controller_module
    import model as model_module
    from config import config

    backend = object.__new__(model_module.Model)
    backend._ocr_lifecycle_lock = RLock()
    backend._ocr_shutdown_requested = False
    backend.ensure_initialized = Mock()
    backend.ocr_pipeline = None
    backend._ocrChatboxDetector = lambda: None
    controller = controller_module.Controller.__new__(controller_module.Controller)
    controller._processMessage = Mock()
    controller._messagePublicationGuard = lambda source: lambda: config.ENABLE_OCR_CAPTURE is True
    monkeypatch.setattr(controller_module, "model", backend)
    monkeypatch.setattr(config, "ENABLE_OCR_CAPTURE", False)
    monkeypatch.setattr(config, "OCR_SOURCE_LANGUAGE", "auto")
    monkeypatch.setattr(config, "OCR_CHATBOX_FILTER", False)
    monkeypatch.setattr(ocr_pipeline.OcrPipeline, "_readerFor",
                        lambda self, spec: Mock(return_value=SimpleNamespace(txts=["hello world"], scores=[0.99], boxes=None)))
    monkeypatch.setattr(ocr_pipeline.ocr_engine, "isAvailable", lambda: True)
    monkeypatch.setattr(ocr_pipeline, "probeCapture", lambda title: "ok")
    monkeypatch.setattr(ocr_pipeline, "BackgroundThreads", Mock())
    thread = Mock()
    capture = SimpleNamespace(get=Mock(return_value=np.zeros((8, 8, 3), np.uint8)), backend="x11")

    def early_tick():
        backend.ocr_pipeline._capture = capture
        backend.ocr_pipeline._tick()
        capture.get.assert_not_called()
        controller._processMessage.assert_not_called()

    thread.start.side_effect = early_tick
    monkeypatch.setattr(ocr_pipeline, "Thread", Mock(return_value=thread))
    assert controller.setEnableOcrCapture() == {"status": 200, "result": True}
    backend.ocr_pipeline._tick()
    backend.ocr_pipeline._tick()
    controller._processMessage.assert_called_once()
    assert len(backend.ocr_pipeline._dedup._items) == 1
    monkeypatch.setattr(config, "ENABLE_OCR_CAPTURE", False)
    assert controller.ocrMessage({"text": "rejected"}) is False
    backend.ocr_pipeline.requestShutdown()
    assert backend.getOCRRuntime()["state"] == "stopped"
