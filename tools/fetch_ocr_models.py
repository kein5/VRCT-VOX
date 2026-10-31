"""Explicit local OCR development helper; never run by fork packaging.

    python tools/fetch_ocr_models.py --root <config dir>/downloaded_models [--language auto] [--yes]

Downloads the pinned PP-OCR catalog entries a chat-reading language needs,
through the same consented, hash-verified manager the app uses (Config →
Chat reading → Download). It prints the source, licence, size and
destination and asks before connecting; --yes records that agreement for
scripted runs. VRCT-VOX never ships these weights in a build.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src-python"))

from models.model_downloads.manager import Downloads  # noqa: E402
from models.ocr.ocr_languages import SELECTABLE_LANGUAGES, resolveModelSpec  # noqa: E402
from models.ocr.ocr_models import isInstalled  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, type=Path, help="downloaded_models directory next to config.json")
    parser.add_argument("--language", default="auto", choices=SELECTABLE_LANGUAGES)
    parser.add_argument("--yes", action="store_true", help="agree to the terms shown without prompting")
    args = parser.parse_args()

    spec = resolveModelSpec(args.language)
    manager = Downloads(args.root)
    rows = {row["id"]: row for row in manager.catalog()["models"]}
    try:
        for model_id in spec.model_ids:
            row = rows[model_id]
            if isInstalled(args.root, model_id):
                print(f"{model_id}: already downloaded at {row['destination']}")
                continue
            print(f"{row['name']} · {row['provider']} · {row['license']} · {row['total_bytes']:,} bytes")
            print("  sources: " + ", ".join(row["sources"]))
            print("  terms:   " + ", ".join(row["licenses"]))
            print(f"  save to: {row['destination']}")
            if not args.yes and input("Download from Hugging Face? [y/N] ").strip().lower() != "y":
                print("skipped")
                return 1
            manager.start({"id": model_id, "consent": True, "catalog_version": manager.catalog_version})
            while (job := manager.state()["jobs"][model_id])["phase"] in ("queued", "downloading", "verifying"):
                time.sleep(0.5)
            print(f"  {job['phase']}" + (f": {job['error_code']}" if job.get("error_code") else ""))
            if job["phase"] != "ready":
                return 1
    finally:
        manager.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
