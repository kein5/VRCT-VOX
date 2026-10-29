"""Reject restricted OCR and private, non-redistributable validation assets."""
import argparse
from pathlib import Path
import zipfile

RESTRICTED_NAME = "chatbox_yolox_tiny.onnx"
PRIVATE_VOICE_NAMES = frozenset('mia2026' + suffix for suffix in ('.pth', '.index', '.zip', '.png'))


def check(paths):
    for path in map(Path, paths):
        if not path.exists():
            raise ValueError(f"Artifact does not exist: {path}")
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                names = [str(path), *archive.namelist()]
        else:
            names = [str(p) for p in path.rglob("*")] if path.is_dir() else [str(path)]
        basenames = {name.replace("\\", "/").split("/")[-1].lower() for name in names}
        if RESTRICTED_NAME in basenames:
            raise ValueError(f"Restricted OCR model in fork distribution: {path}")
        if PRIVATE_VOICE_NAMES & basenames:
            raise ValueError(f"Private voice asset in fork distribution: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    try:
        check(args.paths)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
