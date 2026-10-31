"""Detector-free chat-bubble finding: a user region, PP-OCR text lines, a style check.

The upstream chat-bubble detector (onnx/chatbox_yolox_tiny.onnx) may not ship
in VRCT-VOX or be downloaded for its users, and its outputs may not be used to
train a replacement. Until a VRCT-VOX detector exists, bubbles are found
without one:

1. Region. The user sets a rectangle in relative window coordinates
   (Config → Chat reading). Only that part of the frame is read; the default
   is the whole window.
2. Text lines. PP-OCR's own text detector (DB, run by RapidOCR on the region)
   finds the lines; no extra model is involved.
3. Bubbles. Lines are grouped into blocks: VRChat centres the lines of one
   chatbox and spaces them tightly, so lines that overlap horizontally and sit
   less than about half a line apart belong together. Separate bubbles are
   farther apart (each has its own padding) or side by side.
4. Style. A VRChat chatbox is light text on a dark, translucent panel. A block
   whose glyphs are not much brighter than a dark backdrop is world text (signs,
   UI panels, posters) and is dropped. This can be turned off in Config.

A colour/contour detector for the whole bubble was tried upstream and
disproven on real frames (world UI panels and rock or wood textures were
taken for bubbles), so shape heuristics only ever filter what PP-OCR already
read as text; they never propose regions.

The pipeline treats the candidate source as pluggable: anything with
isAvailable(), loadModel() and detect(frame) -> [(bbox, crop), ...] works.
A future detector returns one crop per bubble and leaves splits_bubbles False.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

BBox = Tuple[int, int, int, int]  # (x, y, w, h)
Region = Tuple[float, float, float, float]  # (x, y, width, height), each 0..1

FULL_REGION: Region = (0.0, 0.0, 1.0, 1.0)
# Smallest region side, relative. Anything smaller cannot hold a readable line.
MIN_REGION_SIDE = 0.02
# Longest side handed to PP-OCR. A 4K window takes over a second per tick on a
# CPU at full size; 2560 keeps small chatbox text (about 1% of the height)
# above the recogniser's 48 px line height after resizing.
MAX_READ_SIDE = 2560

# Line grouping, in multiples of the line height.
LINE_GAP_RATIO = 0.6
MIN_HORIZONTAL_OVERLAP = 0.3

# Style check (0..255 luminance). Measured on rendered chatbox panels: the panel
# is near-black at ~80% opacity, so even over a white world it stays below ~90.
PANEL_MAX_LUMA = 110.0
GLYPH_MIN_LUMA = 165.0
MIN_CONTRAST = 90.0
# Glyphs are white; chroma (max-min channel) above this is coloured world text.
GLYPH_MAX_CHROMA = 60.0


def normalizeRegion(region) -> Region:
    """Clamp a region (dict or 4-sequence) into the frame. Invalid input -> full frame."""
    try:
        if isinstance(region, dict):
            x, y, w, h = (float(region[key]) for key in ("x", "y", "width", "height"))
        else:
            x, y, w, h = (float(value) for value in region)
    except (KeyError, TypeError, ValueError):
        return FULL_REGION
    if not all(np.isfinite(v) for v in (x, y, w, h)):
        return FULL_REGION
    x, y = min(max(x, 0.0), 1.0 - MIN_REGION_SIDE), min(max(y, 0.0), 1.0 - MIN_REGION_SIDE)
    w, h = min(max(w, MIN_REGION_SIDE), 1.0 - x), min(max(h, MIN_REGION_SIDE), 1.0 - y)
    return (x, y, w, h)


def regionToDict(region: Region) -> Dict[str, float]:
    x, y, w, h = region
    return {"x": x, "y": y, "width": w, "height": h}


def regionPixels(region: Region, width: int, height: int) -> BBox:
    x, y, w, h = normalizeRegion(region)
    x0, y0 = int(round(x * width)), int(round(y * height))
    x1, y1 = int(round((x + w) * width)), int(round((y + h) * height))
    x1, y1 = max(x0 + 1, min(width, x1)), max(y0 + 1, min(height, y1))
    return (x0, y0, x1 - x0, y1 - y0)


class RegionCandidates:
    """Candidate source without a detector: the configured region of the frame.

    detect() returns one crop. splits_bubbles tells the pipeline that a crop may
    hold several bubbles (and world text), so OCR lines must be grouped and
    filtered afterwards.
    """

    name = "region"
    splits_bubbles = True

    def __init__(self, region=FULL_REGION, max_side: int = MAX_READ_SIDE) -> None:
        self.region = normalizeRegion(region)
        self.max_side = int(max_side)

    def setRegion(self, region) -> None:
        self.region = normalizeRegion(region)

    def isAvailable(self) -> bool:
        return True

    def loadModel(self) -> None:
        return None

    def detect(self, frame: Optional[np.ndarray]) -> List[Tuple[BBox, np.ndarray]]:
        if frame is None or getattr(frame, "ndim", 0) != 3 or frame.size == 0:
            return []
        height, width = frame.shape[:2]
        x, y, w, h = regionPixels(self.region, width, height)
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            return []
        longest = max(crop.shape[:2])
        if longest > self.max_side and cv2 is not None:
            scale = self.max_side / float(longest)
            crop = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))),
                              interpolation=cv2.INTER_AREA)
        return [((x, y, w, h), np.ascontiguousarray(crop))]


def _box(line: dict) -> Optional[Tuple[float, float, float, float]]:
    try:
        left, right = float(line["left"]), float(line["right"])
        top, bottom = float(line["top"]), float(line["bottom"])
    except (KeyError, TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _sameBubble(a, b) -> bool:
    (al, at, ar, ab), (bl, bt, br, bb) = a, b
    height = min(ab - at, bb - bt)
    gap = max(bt - ab, at - bb, 0.0)
    if gap > LINE_GAP_RATIO * height:
        return False
    overlap = min(ar, br) - max(al, bl)
    return overlap > MIN_HORIZONTAL_OVERLAP * min(ar - al, br - bl)


def groupLines(lines: Sequence[dict]) -> List[List[dict]]:
    """Group OCR lines into bubbles, top to bottom. Lines without a box stay alone."""
    boxed = [(line, _box(line)) for line in lines]
    parent = list(range(len(boxed)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxed)):
        for j in range(i + 1, len(boxed)):
            if boxed[i][1] is not None and boxed[j][1] is not None and _sameBubble(boxed[i][1], boxed[j][1]):
                parent[find(i)] = find(j)

    groups: Dict[int, List[int]] = {}
    for index in range(len(boxed)):
        groups.setdefault(find(index), []).append(index)

    def top(indices: List[int]) -> float:
        boxes = [boxed[i][1] for i in indices if boxed[i][1] is not None]
        return min(b[1] for b in boxes) if boxes else float("inf")

    ordered = sorted(groups.values(), key=lambda indices: (top(indices), indices[0]))
    return [[boxed[i][0] for i in sorted(indices, key=lambda i: ((boxed[i][1] or (0, 0))[1], i))]
            for indices in ordered]


def blockBounds(block: Sequence[dict]) -> Optional[BBox]:
    boxes = [b for b in (_box(line) for line in block) if b is not None]
    if not boxes:
        return None
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return (int(left), int(top), int(np.ceil(right - left)), int(np.ceil(bottom - top)))


def _otsu(values: np.ndarray) -> float:
    histogram = np.bincount(values.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    total = histogram.sum()
    if total == 0:
        return 128.0
    levels = np.arange(256, dtype=np.float64)
    weight = np.cumsum(histogram)
    mean = np.cumsum(histogram * levels)
    between = (mean[-1] * weight - mean * total) ** 2 / np.maximum(weight * (total - weight), 1e-9)
    return float(np.argmax(between))


def looksLikeChatbox(crop: np.ndarray, block: Sequence[dict]) -> bool:
    """True when the block's lines are light, neutral glyphs on a dark panel."""
    if crop is None or getattr(crop, "ndim", 0) != 3:
        return False
    pixels = []
    height, width = crop.shape[:2]
    for line in block:
        box = _box(line)
        if box is None:
            continue
        x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
        x1, y1 = min(width, int(np.ceil(box[2]))), min(height, int(np.ceil(box[3])))
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            pixels.append(crop[y0:y1, x0:x1].reshape(-1, 3))
    if not pixels:
        return False
    bgr = np.concatenate(pixels).astype(np.float32)
    luma = bgr @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
    threshold = _otsu(luma)
    bright, dark = luma > threshold, luma <= threshold
    # Glyph strokes cover well under half of a text line's box; the panel is the rest.
    if not bright.any() or not dark.any() or bright.mean() > 0.6:
        return False
    glyph, panel = float(luma[bright].mean()), float(luma[dark].mean())
    chroma = float((bgr[bright].max(axis=1) - bgr[bright].min(axis=1)).mean())
    return (panel <= PANEL_MAX_LUMA and glyph >= GLYPH_MIN_LUMA
            and glyph - panel >= MIN_CONTRAST and chroma <= GLYPH_MAX_CHROMA)
