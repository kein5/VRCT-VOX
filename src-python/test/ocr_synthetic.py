"""Synthetic VRChat-like frames for OCR tests: a noisy world, chatbox bubbles, world text.

Nothing here touches a real screen or window. Each draw call returns the
line boxes it rendered, so tests can feed a mocked OCR engine with boxes that
match the pixels (the chatbox filter reads those pixels).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).resolve().parents[1] / "models" / "overlay" / "fonts" / "NotoSansJP-Regular.ttf"

# VRChat's chatbox: near-black panel at ~80% opacity, white text.
PANEL_RGBA = (18, 18, 22, 205)
TEXT_RGBA = (255, 255, 255, 255)


def font(size: int = 26):
    return ImageFont.truetype(str(FONT_PATH), size)


class Scene:
    def __init__(self, width: int = 1280, height: int = 720, seed: int = 1) -> None:
        rng = np.random.default_rng(seed)
        base = np.zeros((height, width, 3), np.uint8)
        base[:] = np.linspace(70, 210, width)[None, :, None].astype(np.uint8)
        base = (base.astype(np.int16) + rng.integers(-25, 25, (height, width, 3))).clip(0, 255).astype(np.uint8)
        self.image = Image.fromarray(base).convert("RGBA")
        self.lines: List[dict] = []

    def bubble(self, center_x: int, top: int, lines: List[str], size: int = 26, line_gap: int = 6,
               panel=PANEL_RGBA, text=TEXT_RGBA) -> List[dict]:
        """Draw centred lines on a rounded panel, like VRChat's chatbox."""
        f = font(size)
        overlay = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        boxes, y = [], top
        for line in lines:
            left, t, right, bottom = draw.textbbox((0, 0), line, font=f)
            width, height = right - left, bottom - t
            x = center_x - width // 2
            boxes.append((line, x, y, width, height, left, t))
            y += height + line_gap
        x0 = min(b[1] for b in boxes) - 18
        x1 = max(b[1] + b[3] for b in boxes) + 18
        y0, y1 = top - 12, y - line_gap + 12
        draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=panel)
        out = []
        for line, x, y, width, height, left, t in boxes:
            draw.text((x - left, y - t), line, font=f, fill=text)
            out.append({"text": line, "confidence": 0.99, "left": float(x - 2), "right": float(x + width + 2),
                        "top": float(y - 3), "bottom": float(y + height + 3)})
        self.image = Image.alpha_composite(self.image, overlay)
        self.lines.extend(out)
        return out

    def sign(self, x: int, y: int, text: str, size: int = 30, panel=(235, 225, 200, 255),
             ink=(40, 30, 20, 255)) -> dict:
        """World text: dark letters on a light board (a poster, a menu, a sign)."""
        f = font(size)
        draw = ImageDraw.Draw(self.image)
        left, t, right, bottom = draw.textbbox((0, 0), text, font=f)
        draw.rectangle((x - 10, y - 8, x + (right - left) + 10, y + (bottom - t) + 8), fill=panel)
        draw.text((x - left, y - t), text, font=f, fill=ink)
        line = {"text": text, "confidence": 0.99, "left": float(x - 2), "right": float(x + right - left + 2),
                "top": float(y - 3), "bottom": float(y + bottom - t + 3)}
        self.lines.append(line)
        return line

    def bgr(self) -> np.ndarray:
        return np.ascontiguousarray(np.array(self.image.convert("RGB"))[:, :, ::-1])


def shifted(lines: List[dict], dx: float, dy: float) -> List[dict]:
    """Line boxes relative to a crop whose origin is (dx, dy) in the frame."""
    out = []
    for line in lines:
        moved = dict(line)
        for key, delta in (("left", dx), ("right", dx), ("top", dy), ("bottom", dy)):
            moved[key] = line[key] - delta
        out.append(moved)
    return out


def region_box(region: Tuple[float, float, float, float], width: int, height: int):
    x, y, w, h = region
    return int(round(x * width)), int(round(y * height))
