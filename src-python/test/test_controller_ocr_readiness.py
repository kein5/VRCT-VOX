"""Controller endpoints for detector-free chat reading: region, filter, readiness, model root."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import config
from controller import Controller
from errors import ErrorCode, OcrStartError
from models.ocr.ocr_capture import CAPTURE_OK, CAPTURE_WINDOW_NOT_FOUND


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = Controller.__new__(Controller)
        self.controller.model_downloads = SimpleNamespace(root=Path("/tmp/vrct-test-models"))
        for name in ("OCR_CAPTURE_REGION", "OCR_CHATBOX_FILTER", "OCR_SOURCE_LANGUAGE", "ENABLE_OCR_CAPTURE"):
            self.addCleanup(setattr, config, name, getattr(config, name))


class TestRegionAndFilter(_Base):
    def test_valid_region_is_stored_rounded_and_pushed(self) -> None:
        with patch("controller.model.updateOCRCaptureSettings") as update:
            response = self.controller.setOcrCaptureRegion(
                {"x": 0.1234567, "y": 0.25, "width": 0.5, "height": 0.5})
        self.assertEqual(response["status"], 200)
        self.assertEqual(config.OCR_CAPTURE_REGION, {"x": 0.1235, "y": 0.25, "width": 0.5, "height": 0.5})
        self.assertEqual(self.controller.getOcrCaptureRegion()["result"], config.OCR_CAPTURE_REGION)
        update.assert_called_once()

    def test_invalid_regions_are_rejected_and_change_nothing(self) -> None:
        config.OCR_CAPTURE_REGION = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
        for value in (
            {"x": 0.6, "y": 0.0, "width": 0.6, "height": 1.0},   # leaves the window
            {"x": 0.0, "y": 0.0, "width": 0.001, "height": 1.0},  # too small to read
            {"x": -0.1, "y": 0.0, "width": 0.5, "height": 0.5},
            {"x": 0.0, "y": 0.0, "width": 1.0},
            {"x": True, "y": 0.0, "width": 1.0, "height": 1.0},
            {"x": "0", "y": 0.0, "width": 1.0, "height": 1.0},
            [0, 0, 1, 1],
        ):
            with patch("controller.model.updateOCRCaptureSettings") as update:
                response = self.controller.setOcrCaptureRegion(value)
            self.assertEqual(response["status"], 400, value)
            update.assert_not_called()
        self.assertEqual(config.OCR_CAPTURE_REGION, {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0})

    def test_chatbox_filter_toggles(self) -> None:
        with patch("controller.model.updateOCRCaptureSettings") as update:
            self.assertEqual(self.controller.setDisableOcrChatboxFilter()["result"], False)
            self.assertEqual(self.controller.getOcrChatboxFilter()["result"], False)
            self.assertEqual(self.controller.setEnableOcrChatboxFilter()["result"], True)
        self.assertEqual(update.call_count, 2)


class TestReadiness(_Base):
    def test_reports_missing_models_and_window(self) -> None:
        config.OCR_SOURCE_LANGUAGE = "Korean"
        with patch("controller.ocr_capture.probeCapture", return_value=CAPTURE_WINDOW_NOT_FOUND), \
                patch("controller.ocr_models.missingModels", return_value=["ppocrv6-small", "ppocrv5-korean"]) as missing:
            result = self.controller.getOcrReadiness()["result"]
        self.assertEqual(missing.call_args.args[0], Path("/tmp/vrct-test-models"))
        self.assertEqual(result["required_models"], ["ppocrv6-small", "ppocrv5-korean"])
        self.assertEqual(result["missing_models"], ["ppocrv6-small", "ppocrv5-korean"])
        self.assertEqual(result["capture"], CAPTURE_WINDOW_NOT_FOUND)
        self.assertTrue(result["language_supported"])

    def test_ready(self) -> None:
        config.OCR_SOURCE_LANGUAGE = "auto"
        with patch("controller.ocr_capture.probeCapture", return_value=CAPTURE_OK), \
                patch("controller.ocr_models.missingModels", return_value=[]), \
                patch("controller.ocr_engine.isAvailable", return_value=True):
            result = self.controller.getOcrReadiness()["result"]
        self.assertEqual((result["engine"], result["missing_models"], result["capture"]), (True, [], CAPTURE_OK))


class TestStartUsesDownloads(_Base):
    def test_model_root_is_the_download_root(self) -> None:
        config.ENABLE_OCR_CAPTURE = False
        with patch("controller.model.startOCRCapture", return_value=True) as start:
            self.assertEqual(self.controller.setEnableOcrCapture()["result"], True)
        self.assertEqual(start.call_args.kwargs["model_root"], Path("/tmp/vrct-test-models"))

    def test_new_reasons_reach_the_toggle(self) -> None:
        self.controller.run = Mock()
        self.controller.run_mapping = {"enable_ocr_capture": "/run/enable_ocr_capture"}
        for code in (ErrorCode.OCR_DISABLED_MODEL_MISSING, ErrorCode.OCR_DISABLED_WINDOW_NOT_FOUND,
                     ErrorCode.OCR_DISABLED_CAPTURE_UNAVAILABLE):
            config.ENABLE_OCR_CAPTURE = False
            with patch("controller.model.startOCRCapture", side_effect=OcrStartError(code)):
                self.assertEqual(self.controller.setEnableOcrCapture()["result"], False)
            status, endpoint, result = self.controller.run.call_args.args
            self.assertEqual((status, endpoint, result["error_code"]), (400, "/run/enable_ocr_capture", code.value))


class TestApplyOcrDownload(unittest.TestCase):
    def test_ocr_downloads_need_no_path_setting(self) -> None:
        controller = Controller.__new__(Controller)
        calls = []

        def apply(id, job_id, callback):
            callback(SimpleNamespace(target="ocr"), {"det": "/x/det.onnx"})
            calls.append(id)
            return {"jobs": {}}

        controller.model_downloads = SimpleNamespace(apply=apply)
        response = controller.applyModelDownload({"id": "ppocrv6-small", "job_id": "j", "expected": {}})
        self.assertEqual(response["status"], 200)
        self.assertEqual(calls, ["ppocrv6-small"])
        bad = controller.applyModelDownload({"id": "ppocrv6-small", "job_id": "j", "expected": {"model": "x"}})
        self.assertEqual(bad["status"], 400)


if __name__ == "__main__":
    unittest.main()
