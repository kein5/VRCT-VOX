import zipfile
import argparse
from pathlib import Path
import time
import os
import tempfile
import sys
from tqdm import tqdm # tqdmをインポート

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_voice_distribution import check

def zip_files_and_directory(zip_name, file_paths, dir_paths, verbose=False):
    # Reject missing inputs and stale forbidden resources before touching a
    # previous candidate. A partial ZIP must never masquerade as a release.
    check([*file_paths, *dir_paths])
    output = Path(zip_name)
    entries = []
    for value in file_paths:
        path = Path(value)
        if not path.is_file():
            raise ValueError(f"Not an input file: {path}")
        entries.append((path, path.name))
    for value in dir_paths:
        path = Path(value)
        if not path.is_dir():
            raise ValueError(f"Not an input directory: {path}")
        entries.extend((item, Path(path.name) / item.relative_to(path))
                       for item in path.rglob("*") if item.is_file())
    if not entries:
        raise ValueError("No package inputs")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, name in tqdm(entries, desc="Packaging", unit="file"):
                archive.write(path, name)
                if verbose:
                    print(f"Add: {name}")
        check([temporary])
        os.replace(temporary, output)
        print(f"Created and inspected: {output}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    start_time = time.time()
    parser = argparse.ArgumentParser(description="Create a zip file from specified files and directories.")
    parser.add_argument("--zip_name", type=str, default="VRCT-VOX.zip", help="Name of the output zip file.")
    parser.add_argument(
        "--file_paths",
        type=str,
        nargs="*",
        default=["src-tauri/target/release/vrct-vox.exe", "src-tauri/target/release/vrct-vox-sidecar.exe"],
        help="List of file paths to include in the zip."
    )
    parser.add_argument(
        "--dir_paths",
        type=str,
        nargs="*",
        default=["src-tauri/target/release/_internal"],
        help="List of directory paths to include in the zip."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Increase output verbosity."
    )
    args = parser.parse_args()

    zip_files_and_directory(args.zip_name, args.file_paths, args.dir_paths, args.verbose)
    end_time = time.time()
    processing_time = end_time - start_time
    print(f"Complete! Processing time: {processing_time:.2f} seconds")
