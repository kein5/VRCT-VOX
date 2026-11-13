"""VRCT-VOX's own chatbox detector, loaded only from its verified download.

The model is a YOLOX-Tiny trained from VRCT-VOX's own frames (tools/chatbox_lab)
and published under MIT. It has the same input and output layout as the upstream
VRCT detector, so BubbleDetector (letterbox, decode, NMS) runs it unchanged.

The upstream detector (onnx/chatbox_yolox_tiny.onnx, onnx/NOTICE.txt) must never
run in VRCT-VOX. BubbleDetector falls back to that file when it is given no
path, so this module is the only place that constructs one, and only:

- with the path ocr_models.resolveArtifact returns for the catalog entry
  `vrct-vox-chatbox-detector`, after its size and sha256 matched the catalog;
- when the file name is `vrct_vox_chatbox_yolox_tiny.onnx` (never the
  upstream name) and the file is not inside the bundled onnx directory.

findModelPath() is never called here.

With a detector, every detected chatbox is read on its own (one crop per
bubble). OcrPipeline still applies the reading area (detections whose centre
lies outside it are dropped) and the chatbox-style filter (per crop).
"""

from __future__ import annotations

from os import path as os_path
import sys
from typing import Optional

from ..model_downloads.catalog import DETECTOR_FILE_NAME, DETECTOR_MODEL_ID
from . import ocr_bubble_detector
from .ocr_bubble_detector import BubbleDetector
from .ocr_models import OcrModelsInvalid, OcrModelsMissing, isInstalled, resolveArtifact

try:
    from utils import errorLogging, printLog
except Exception:  # pragma: no cover
    def errorLogging():
        import traceback
        print(traceback.format_exc())

    def printLog(*args, **kwargs):
        print(*args, **kwargs)


# Measured on the chatbox_lab validation split: 39 of 41 chatboxes, 1 extra, 39 ms on CPU.
DETECTOR_CONFIDENCE = 0.7
UPSTREAM_FILE_NAME = ocr_bubble_detector.MODEL_FILE_NAME


def _bundledDirectories():
    """Where the upstream detector is shipped or checked out. Nothing in them may load."""
    directories = [os_path.join(os_path.dirname(os_path.abspath(ocr_bubble_detector.__file__)), "onnx")]
    if getattr(sys, "frozen", False):
        directories.append(os_path.join(os_path.dirname(sys.executable), "_internal", "ocr_onnx"))
    return [os_path.normcase(os_path.realpath(d)) for d in directories]


def isAllowedModelPath(model_path) -> bool:
    """True only for our detector's file name outside the upstream model directories."""
    if not isinstance(model_path, str) or not model_path:
        return False
    name = os_path.basename(model_path)
    if name != DETECTOR_FILE_NAME or name.lower() == UPSTREAM_FILE_NAME.lower():
        return False
    directory = os_path.normcase(os_path.realpath(os_path.dirname(os_path.abspath(model_path))))
    return directory not in _bundledDirectories()


class ChatboxDetector:
    """Candidate source for OcrPipeline: one (bbox, crop) per detected chatbox."""

    name = "vrct-vox-chatbox"
    splits_bubbles = False

    def __init__(self, model_path: str, confidence: float = DETECTOR_CONFIDENCE) -> None:
        if not isAllowedModelPath(model_path):
            raise ValueError("only the verified VRCT-VOX chatbox detector may be loaded")
        self.model_path = model_path
        self._inner = BubbleDetector(model_path=model_path, confidence=confidence)
        # BubbleDetector substitutes the upstream file for an empty path; make sure it did not.
        if self._inner.model_path != model_path:
            raise ValueError("only the verified VRCT-VOX chatbox detector may be loaded")

    def isAvailable(self) -> bool:
        return self._inner.isAvailable()

    def loadModel(self):
        return self._inner.loadModel()

    def detect(self, frame):
        return self._inner.detect(frame)


def isDetectorInstalled(root) -> bool:
    """The download is complete (sizes only; the hash is checked when it is used)."""
    return isInstalled(root, DETECTOR_MODEL_ID)


def buildChatboxDetector(root) -> Optional[ChatboxDetector]:
    """Our detector from the verified download, or None (not downloaded, or files changed)."""
    try:
        return ChatboxDetector(resolveArtifact(root, DETECTOR_MODEL_ID, "detector"))
    except OcrModelsMissing:
        return None
    except (OcrModelsInvalid, OSError, ValueError):
        errorLogging()
        printLog("OCR: the chatbox detector download does not match the catalog; reading without it")
        return None
