"""Regenerate the app screenshots used by the user documentation (site/).

    python tools/docs_screenshots.py --python build/dev/browser-venv/bin/python \
        --chromium /path/to/chrome

Renders the production main screen and settings pages in Japanese and English
through tests/voice/studio-entry with an offline sidecar peer (no models, no
audio), and writes WebP images to site/public/screenshots/{ja,en}/. Needs the
browser test environment (`python tools/dev.py setup --scope browser`), a
Chromium executable and the UI's node_modules. Run it after UI changes and
commit the images with the change.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "public" / "screenshots"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", required=True, help="Python of the browser test environment")
    parser.add_argument("--chromium", required=True, help="Chromium executable for Playwright")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    env = dict(os.environ, VRCT_TEST_STUDIO_UI="1", VRCT_TEST_CHROMIUM=args.chromium,
               VRCT_DOCS_SCREENSHOTS=str(args.output.resolve()))
    command = [args.python, "-m", "pytest", "-c", "tests/voice/pytest.ini", "tests/voice/test_docs_screenshots.py", "-q"]
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode == 0:
        total = sum(f.stat().st_size for f in args.output.rglob("*.webp"))
        print(f"wrote {args.output} ({total / 1024:.0f} KiB)")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
