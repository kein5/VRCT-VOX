"""OCR handler regressions with fake readers/capture and isolated model state."""

from threading import Event, Lock, Thread, current_thread
from types import SimpleNamespace
from unittest.mock import Mock
import time

import pytest

import controller as controller_module
import model as model_module
from config import config
from controller import Controller
from models.ocr.ocr_models import OcrModelsInvalid, OcrModelsMissing
from models.ocr.ocr_pipeline import OcrPipeline
from models.ocr import ocr_pipeline


@pytest.fixture
def subject(monkeypatch, tmp_path):
    backend = object.__new__(model_module.Model)
    backend._ocr_lifecycle_lock = Lock()
    backend._ocr_shutdown_requested = False
    backend.ensure_initialized = Mock()
    backend.ocr_pipeline = None
    backend._ocrDetectorChange = Mock(return_value={})
    backend._ocrChatboxDetector = Mock(return_value=None)
    controller = Controller.__new__(Controller)
    controller.model_downloads = SimpleNamespace(root=tmp_path, request_close=lambda: None, close=lambda: True)
    controller.run = Mock()
    controller.run_mapping = {"enable_ocr_capture": "/run/enable_ocr_capture"}
    monkeypatch.setattr(controller_module, "model", backend)
    monkeypatch.setattr(config, "OCR_SOURCE_LANGUAGE", "auto")
    monkeypatch.setattr(config, "ENABLE_OCR_CAPTURE", False)
    # No unexpected test path may construct an actual inference engine.
    reader = Mock(side_effect=AssertionError("unexpected reader load"))
    monkeypatch.setattr(model_module.ocr_engine, "getReader", reader)
    return controller, backend, reader


def active_pipeline(controller, backend):
    pipeline = OcrPipeline(callback=controller.ocrMessage)
    pipeline._reader = object()
    pipeline._thread = Mock()
    pipeline._thread.is_alive.return_value = True
    backend.ocr_pipeline = pipeline
    config.ENABLE_OCR_CAPTURE = True
    return pipeline


def test_missing_language_models_reject_before_saving_while_active(subject):
    controller, backend, get_reader = subject
    pipeline = active_pipeline(controller, backend)
    old_reader = pipeline._reader
    response = controller.setOcrSourceLanguage("Korean")
    assert response["status"] == 400
    assert response["result"]["error_code"] == "OCR_DISABLED_MODEL_MISSING"
    assert response["result"]["data"] == "auto"
    assert config.OCR_SOURCE_LANGUAGE == "auto"
    assert config.ENABLE_OCR_CAPTURE is True
    get_reader.assert_not_called()
    pipeline._applyPending()
    assert pipeline._source_language == "auto"
    assert pipeline._reader is old_reader
    assert not pipeline._pending


def test_valid_language_prepares_then_swaps_without_a_deferred_load(subject, monkeypatch):
    controller, backend, get_reader = subject
    pipeline = active_pipeline(controller, backend)
    old_reader, new_reader = pipeline._reader, object()
    resolve = Mock(return_value="verified-files")
    monkeypatch.setattr(model_module, "resolveModelFiles", resolve)
    get_reader.side_effect = None
    get_reader.return_value = new_reader
    response = controller.setOcrSourceLanguage("Korean")
    assert response == {"status": 200, "result": "Korean"}
    assert config.OCR_SOURCE_LANGUAGE == "Korean"
    assert pipeline._reader is old_reader
    assert resolve.call_args.args[0] == controller.model_downloads.root
    assert get_reader.call_args.args[1] == "verified-files"
    # An unrelated setting must not replace the prepared language request.
    backend.updateOCRCaptureSettings()
    pipeline._readerFor = Mock(side_effect=AssertionError("deferred load"))
    pipeline._applyPending()
    assert pipeline._source_language == "Korean"
    assert pipeline._reader is new_reader
    get_reader.assert_called_once()
    pipeline._readerFor.assert_not_called()


@pytest.mark.parametrize("failure, code", [
    (None, "OCR_DISABLED_MODEL_LOAD_FAILED"),
    (OcrModelsMissing(["ocr-korean"]), "OCR_DISABLED_MODEL_MISSING"),
    (OcrModelsInvalid("hash mismatch"), "OCR_DISABLED_MODEL_LOAD_FAILED"),
    (RuntimeError("native reader failed"), "OCR_DISABLED_MODEL_LOAD_FAILED"),
])
def test_load_failure_returns_old_value_without_deferred_rollback(subject, monkeypatch, failure, code):
    controller, backend, get_reader = subject
    pipeline = active_pipeline(controller, backend)
    old_reader = pipeline._reader
    monkeypatch.setattr(model_module, "resolveModelFiles", Mock(return_value="verified-files"))
    get_reader.side_effect = failure
    get_reader.return_value = None
    response = controller.setOcrSourceLanguage("Korean")
    assert response["status"] == 400
    assert response["result"]["error_code"] == code
    assert response["result"]["data"] == "auto"
    assert config.OCR_SOURCE_LANGUAGE == "auto"
    pipeline._applyPending()
    assert pipeline._reader is old_reader
    assert pipeline._source_language == "auto"


def test_stopped_language_change_is_saved_so_its_models_can_be_offered(subject, monkeypatch):
    # The download list follows the selected language; start reports missing files.
    controller, _, get_reader = subject
    resolve = Mock(side_effect=OcrModelsInvalid("hash mismatch"))
    monkeypatch.setattr(model_module, "resolveModelFiles", resolve)
    response = controller.setOcrSourceLanguage("Korean")
    assert response == {"status": 200, "result": "Korean"}
    assert config.OCR_SOURCE_LANGUAGE == "Korean"
    resolve.assert_not_called()
    get_reader.assert_not_called()


def test_latest_language_including_return_to_active_wins(subject, monkeypatch):
    controller, backend, get_reader = subject
    pipeline = active_pipeline(controller, backend)
    old_reader = pipeline._reader
    monkeypatch.setattr(model_module, "resolveModelFiles", Mock(return_value="verified-files"))
    get_reader.side_effect = [object(), old_reader]
    assert controller.setOcrSourceLanguage("Korean")["status"] == 200
    assert controller.setOcrSourceLanguage("auto")["status"] == 200
    pipeline._applyPending()
    assert (config.OCR_SOURCE_LANGUAGE, pipeline._source_language) == ("auto", "auto")
    assert pipeline._reader is old_reader


def test_pipeline_config_can_cancel_a_pending_language_switch(subject):
    controller, backend, _ = subject
    pipeline = active_pipeline(controller, backend)
    old_reader = pipeline._reader
    pipeline._readerFor = Mock(return_value=object())
    pipeline.applyConfig({"source_language": "Korean"})
    pipeline.applyConfig({"source_language": "auto"})
    pipeline._applyPending()
    assert pipeline._source_language == "auto"
    assert pipeline._reader is old_reader
    pipeline._readerFor.assert_called_once()


def test_stopping_before_initialization_does_not_initialize_services(subject):
    _, backend, _ = subject
    backend.stopOCRCapture()
    backend.ensure_initialized.assert_not_called()


def shutdown_services(controller, backend, monkeypatch):
    """Only the OCR lifecycle is real; other services never initialize."""
    services = Mock()
    services.checkKeywords.return_value = False
    services.requestOCRShutdown.side_effect = backend.requestOCRShutdown
    services.stopOCRCapture.side_effect = backend.stopOCRCapture
    monkeypatch.setattr(controller_module, "model", services)
    monkeypatch.setattr(controller_module, "device_manager", Mock())
    controller._closeRealtimeASR = Mock(return_value=True)
    controller.mic_lifecycle_lock = Lock()
    controller.speaker_lifecycle_lock = Lock()
    return services


@pytest.mark.parametrize("blocked", [False, True])
def test_shutdown_stops_capture_within_bound_and_suppresses_late_callbacks(subject, monkeypatch, blocked):
    controller, backend, _ = subject
    entered, release = Event(), Event()
    closed_on = []

    class Capture:
        def __init__(self, **kwargs):
            self.owner = current_thread()

        def get(self):
            entered.set()
            if blocked:
                assert release.wait(3)
            return None

        def close(self):
            closed_on.append(current_thread())
            assert current_thread() is self.owner

    monkeypatch.setattr(ocr_pipeline, "OcrCapture", Capture)
    monkeypatch.setattr(ocr_pipeline, "lowerCurrentThread", lambda: None)
    callback = Mock()
    pipeline = OcrPipeline(callback=callback, poll_interval_ms=5000)
    pipeline._reader = object()
    backend.ocr_pipeline = pipeline
    config.ENABLE_OCR_CAPTURE = True
    worker = Thread(target=pipeline._run, daemon=True)
    pipeline._thread = worker
    services = shutdown_services(controller, backend, monkeypatch)
    monkeypatch.setattr(controller_module, "_SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC", 0.05)

    def dependency_stopped():
        assert pipeline._stop_event.is_set()
        assert not config.ENABLE_OCR_CAPTURE

    services.stopTranslationExecutor.side_effect = dependency_stopped
    services.shutdownOverlay.side_effect = dependency_stopped
    worker.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        assert controller.shutdown() == {"status": 200, "result": True}
        assert time.monotonic() - started < 1
        assert backend._ocr_shutdown_requested
        assert controller.setEnableOcrCapture() == {"status": 200, "result": False}
        assert not backend.startOCRCapture(callback)
        pipeline._emit("late result")
        callback.assert_not_called()
        if blocked:
            assert backend.ocr_pipeline is pipeline  # retain ownership until exit
        else:
            assert not worker.is_alive()
            assert backend.ocr_pipeline is None
    finally:
        release.set()
        worker.join(2)
        backend.stopOCRCapture()
    assert not worker.is_alive()
    assert closed_on == [worker]
    pipeline._emit("after exit")
    callback.assert_not_called()


def test_shutdown_during_reader_load_cannot_start_capture(subject, monkeypatch):
    controller, backend, get_reader = subject
    entered, release = Event(), Event()
    monkeypatch.setattr(ocr_pipeline, "resolveModelFiles", Mock(return_value="verified-files"))
    monkeypatch.setattr(ocr_pipeline.ocr_engine, "isAvailable", lambda: True)
    capture = Mock(side_effect=AssertionError("capture after shutdown"))
    monkeypatch.setattr(ocr_pipeline, "OcrCapture", capture)
    monkeypatch.setattr(ocr_pipeline, "probeCapture", capture)
    monkeypatch.setattr(ocr_pipeline, "BackgroundThreads", Mock())

    def load(*args):
        entered.set()
        assert release.wait(3)
        return object()

    get_reader.side_effect = load
    result = []
    starter = Thread(target=lambda: result.append(controller.setEnableOcrCapture()), daemon=True)
    starter.start()
    try:
        assert entered.wait(1)
        shutdown_services(controller, backend, monkeypatch)
        monkeypatch.setattr(controller_module, "_SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC", 0.05)
        started = time.monotonic()
        assert controller.shutdown()["status"] == 200
        assert time.monotonic() - started < 1
    finally:
        release.set()
        starter.join(2)
        backend.stopOCRCapture()
    assert result == [{"status": 200, "result": False}]
    assert config.ENABLE_OCR_CAPTURE is False
    capture.assert_not_called()


def test_shutdown_during_language_preparation_does_not_save_or_swap(subject, monkeypatch):
    controller, backend, get_reader = subject
    pipeline = active_pipeline(controller, backend)
    # No real thread is needed: the handler, not inference, is blocked here.
    pipeline._thread.is_alive.return_value = True
    old_reader = pipeline._reader
    entered, release = Event(), Event()
    monkeypatch.setattr(model_module, "resolveModelFiles", Mock(return_value="verified-files"))

    def load(*args):
        entered.set()
        assert release.wait(3)
        return object()

    get_reader.side_effect = load
    result = []
    setter = Thread(target=lambda: result.append(controller.setOcrSourceLanguage("Korean")), daemon=True)
    setter.start()
    try:
        assert entered.wait(1)
        shutdown_services(controller, backend, monkeypatch)
        monkeypatch.setattr(controller_module, "_SHUTDOWN_SERVICE_STOP_TIMEOUT_SEC", 0.05)
        assert controller.shutdown()["status"] == 200
    finally:
        release.set()
        setter.join(2)
    assert not setter.is_alive()
    assert result == [{"status": 423, "result": "auto"}]
    assert config.OCR_SOURCE_LANGUAGE == "auto"
    assert pipeline._reader is old_reader
    assert not pipeline._pending


def test_ocr_translation_finishing_after_shutdown_cannot_publish(subject, monkeypatch):
    controller, backend, _ = subject
    services = shutdown_services(controller, backend, monkeypatch)
    entered, release = Event(), Event()
    monkeypatch.setattr(config, "ENABLE_TRANSLATION", True)
    config.ENABLE_OCR_CAPTURE = True

    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return ["translation"], [True], ["translated"]

    services.getOutputTranslate.side_effect = translate
    worker = Thread(target=lambda: controller.ocrMessage({"text": "hello", "language": "English"}), daemon=True)
    worker.start()
    try:
        assert entered.wait(1)
        controller.shutdown()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    controller.run.assert_not_called()
    services.addTranslationHistory.assert_not_called()
    controller.ocrMessage({"text": "another late result"})
    services.getOutputTranslate.assert_called_once()
