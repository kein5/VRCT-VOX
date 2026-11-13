"""Turn labeled lab sessions into COCO JSON for YOLOX.

    python tools/chatbox_lab/yolox/prepare.py

Reads every session under ~/.cache/vrct-vox-chatbox-lab/dataset/raw that
label.py has labeled, and writes dataset/annotations/instances_{train,val}.json.
Images are referenced, not copied. Frames from the same minute look alike, so
the split takes whole one-minute blocks for validation instead of single frames.

Adapted from upstream VRCT's tools/prepare_yolox_dataset.py (MIT).
"""
import json
import random
from pathlib import Path

DATASET = Path.home() / '.cache/vrct-vox-chatbox-lab/dataset'
CATEGORIES = [{'id': 1, 'name': 'chatbox', 'supercategory': 'chatbox'}]
VAL_SHARE = 0.15


def frames():
    for session in sorted((DATASET / 'raw').iterdir()):
        index = session / 'frames.jsonl'
        if not (session / 'labels').is_dir() or not index.is_file():
            continue
        for line in index.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            label = session / 'labels' / (Path(row['file']).stem + '.txt')
            if label.is_file():
                yield session, row, label


def coco(entries):
    images, annotations = [], []
    for image_id, (session, row, label) in enumerate(entries, start=1):
        height, width = row['shape'][:2]
        images.append({'id': image_id, 'file_name': f'raw/{session.name}/{row["file"]}', 'width': width, 'height': height})
        for fields in (line.split() for line in label.read_text().splitlines() if line.strip()):
            cx, cy, bw, bh = (float(v) for v in fields[1:5])
            w, h = bw * width, bh * height
            annotations.append({'id': len(annotations) + 1, 'image_id': image_id, 'category_id': 1,
                                'bbox': [(cx - bw / 2) * width, (cy - bh / 2) * height, w, h],
                                'area': w * h, 'iscrowd': 0})
    return {'images': images, 'annotations': annotations, 'categories': CATEGORIES}


def main():
    entries = list(frames())
    blocks = sorted({(s.name, int(r['time'] // 60)) for s, r, _ in entries})
    val_blocks = set(random.Random(0).sample(blocks, max(1, round(len(blocks) * VAL_SHARE))))
    split = {'train': [], 'val': []}
    for entry in entries:
        split['val' if (entry[0].name, int(entry[1]['time'] // 60)) in val_blocks else 'train'].append(entry)
    out = DATASET / 'annotations'
    out.mkdir(exist_ok=True)
    for name, items in split.items():
        data = coco(items)
        (out / f'instances_{name}.json').write_text(json.dumps(data))
        positives = len({a['image_id'] for a in data['annotations']})
        print(f'{name}: {len(data["images"])} images ({positives} with a chatbox), {len(data["annotations"])} boxes')


if __name__ == '__main__':
    main()
