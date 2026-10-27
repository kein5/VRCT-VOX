"""Fail a fork package containing the restricted upstream OCR model."""
import argparse
from pathlib import Path
import zipfile

RESTRICTED_NAME = "chatbox_yolox_tiny.onnx"


def check(paths):
    for path in map(Path, paths):
        if not path.exists():
            raise ValueError(f"Artifact does not exist: {path}")
        if path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        else:
            names = [str(p) for p in path.rglob("*")] if path.is_dir() else [str(path)]
        if any(name.replace("\\", "/").split("/")[-1].lower() == RESTRICTED_NAME for name in names):
            raise ValueError(f"Restricted OCR model in fork distribution: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    try:
        check(args.paths)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
