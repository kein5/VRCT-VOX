"""VRChat chat-bubble OCR pipeline.

Captures the VRChat window (HWND or the OpenVR compositor mirror on Windows,
X11/XWayland on Linux), finds chat bubbles with VRCT-VOX's own chatbox
detector when the user downloaded it (ocr_chatbox_detector.py), or else without
a detector model (a configured region, PP-OCR text lines, a chatbox-style check;
see ocr_detection.py), reads them with RapidOCR on PP-OCR models the user
downloaded with consent, deduplicates the results, and emits the text via a
callback into the existing translation -> UI/overlay pipeline.
"""

from .ocr_pipeline import OcrPipeline

__all__ = ["OcrPipeline"]
