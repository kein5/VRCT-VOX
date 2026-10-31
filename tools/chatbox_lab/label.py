"""Label collected chatbox frames automatically.

Each frame was saved with the text that the speaker had on screen. PP-OCR
finds text lines, the lines are grouped into blocks as in VRCT-VOX's
detector-free reader, and the block whose text matches the sent text becomes
the chatbox. Its box is the block bounds padded by a fraction of the line
height, which is where the chatbox panel extends beyond the text.

    python tools/chatbox_lab/label.py ~/.cache/vrct-vox-chatbox-lab/dataset/raw/<session>

Writes labels.jsonl, YOLO labels for frames that are safe to train on, and
review.png, a sample with the boxes drawn.
"""
import argparse
import difflib
import json
import random
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src-python'))
from models.ocr.ocr_detection import groupLines
from models.ocr.ocr_engine_rapidocr import getReader, readtext_bgr
from models.ocr.ocr_languages import BASE_MODEL_ID, resolveModelSpec
from models.ocr.ocr_models import resolveModelFiles

MODELS = Path.home() / '.cache/vrct-vox-chatbox-lab/models'
PAD_X, PAD_Y = 0.6, 0.45  # of the median line height
MATCH, UNSURE = 0.6, 0.3


def normalize(text: str) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFKC', text).lower() if not ch.isspace())


def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def lines_text(lines) -> str:
    return ''.join(line['text'] for line in sorted(lines, key=lambda line: (line['top'], line['left'])))


def contained(line: str, text: str) -> float:
    """Share of the line's characters that also appear, in order, in the text."""
    a, b = normalize(line), normalize(text)
    if not a or not b:
        return 0.0
    matched = sum(block.size for block in difflib.SequenceMatcher(None, a, b).get_matching_blocks())
    return matched / len(a)


def chatbox_box(lines, width, height):
    left, top = min(line['left'] for line in lines), min(line['top'] for line in lines)
    right, bottom = max(line['right'] for line in lines), max(line['bottom'] for line in lines)
    heights = sorted(line['bottom'] - line['top'] for line in lines)
    height_px = heights[len(heights) // 2]
    return [max(0, left - PAD_X * height_px), max(0, top - PAD_Y * height_px),
            min(width, right + PAD_X * height_px), min(height, bottom + PAD_Y * height_px)]


def label_frame(reader, image: Image.Image, text: str, recent: list):
    width, height = image.size
    bgr = np.asarray(image.convert('RGB'))[:, :, ::-1].copy()
    lines = [line for line in readtext_bgr(reader, bgr, min_confidence=0.4) if 'top' in line]
    if not text:
        # A negative must not still show an earlier message fading out.
        stale = any(contained(line['text'], old) >= 0.8 and len(normalize(line['text'])) >= 3
                    for line in lines for old in recent if old)
        return {'status': 'stale' if stale else 'negative', 'boxes': []}
    # Keep only lines that belong to the message, so the nameplate and signs
    # next to the chatbox stay out of its box; then keep the group they form.
    own = [line for line in lines if contained(line['text'], text) >= 0.6]
    groups = sorted((g for g in groupLines(own) if g), key=lambda g: -len(normalize(lines_text(g))))
    if not groups:
        return {'status': 'missed', 'boxes': [], 'score': 0.0}
    group = groups[0]
    score = similarity(lines_text(group), text)
    status = 'labeled' if score >= MATCH else 'unsure' if score >= UNSURE else 'missed'
    return {'status': status, 'score': round(score, 3), 'read': lines_text(group),
            'boxes': [chatbox_box(group, width, height)] if status != 'missed' else []}


def write_yolo(path: Path, boxes, width, height):
    rows = []
    for left, top, right, bottom in boxes:
        rows.append(f'0 {(left + right) / 2 / width:.6f} {(top + bottom) / 2 / height:.6f} '
                    f'{(right - left) / width:.6f} {(bottom - top) / height:.6f}')
    path.write_text('\n'.join(rows) + ('\n' if rows else ''))


def review_sheet(session: Path, rows, count=16):
    picks = random.Random(0).sample(rows, min(count, len(rows)))
    tiles = []
    for row in picks:
        image = Image.open(session / row['file']).convert('RGB')
        draw = ImageDraw.Draw(image)
        for box in row['boxes']:
            draw.rectangle(box, outline=(255, 40, 40), width=4)
        draw.text((12, 12), f"{row['status']} {row.get('score', '')}", fill=(255, 255, 0))
        tiles.append(image.resize((640, int(640 * image.height / image.width))))
    if not tiles:
        return
    columns = 4
    tile_h = max(t.height for t in tiles)
    sheet = Image.new('RGB', (640 * columns, tile_h * ((len(tiles) + columns - 1) // columns)))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % columns) * 640, (i // columns) * tile_h))
    sheet.save(session / 'review.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('session', type=Path)
    args = parser.parse_args()
    spec = resolveModelSpec('Japanese') or resolveModelSpec(BASE_MODEL_ID)
    reader = getReader(spec, resolveModelFiles(MODELS, spec))
    if reader is None:
        raise SystemExit('PP-OCR is unavailable')
    frames = [json.loads(line) for line in (args.session / 'frames.jsonl').read_text(encoding='utf-8').splitlines()]
    labels_dir = args.session / 'labels'
    labels_dir.mkdir(exist_ok=True)
    rows, counts = [], {}
    for i, frame in enumerate(frames):
        image = Image.open(args.session / frame['file'])
        recent = [f['text'] for f in frames[max(0, i - 3):i]]
        result = {'file': frame['file'], 'text': frame['text'], **label_frame(reader, image, frame['text'], recent)}
        rows.append(result)
        counts[result['status']] = counts.get(result['status'], 0) + 1
        # Only confident chatboxes and clean negatives are used for training.
        if result['status'] in ('labeled', 'negative'):
            write_yolo(labels_dir / (Path(frame['file']).stem + '.txt'), result['boxes'], *image.size)
    with open(args.session / 'labels.jsonl', 'w', encoding='utf-8') as out:
        out.writelines(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
    review_sheet(args.session, rows)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
