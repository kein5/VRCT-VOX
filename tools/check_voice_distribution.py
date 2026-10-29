"""Reject OCR weights and private validation assets in fork distributions.

Inspect trees and ZIPs (including nested ZIPs). NSIS requires an explicit
--nsis and 7-Zip; unknown or nested installer containers fail closed. This is
a path inventory check, not detection of renamed weights hidden in binaries.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

try:
    from .distribution_policy import ARCHIVE_SUFFIXES, violation
except ImportError:
    from distribution_policy import ARCHIVE_SUFFIXES, violation

MAX_NESTED_ZIP = 128 * 1024 * 1024


def _check_name(name, context):
    reason = violation(name)
    if reason:
        raise ValueError(f"{reason} in fork distribution: {context}: {name}")


def _zip(stream, context, depth=0):
    if depth > 4:
        raise ValueError(f"Cannot inspect excessive ZIP nesting: {context}")
    try:
        with zipfile.ZipFile(stream) as archive:
            for entry in archive.infolist():
                name = entry.filename
                _check_name(name, context)
                if entry.flag_bits & 1:
                    raise ValueError(f"Cannot inspect encrypted ZIP: {context}")
                if name.lower().endswith(".zip"):
                    if entry.file_size > MAX_NESTED_ZIP:
                        raise ValueError(f"Cannot inspect oversized nested ZIP: {context}: {name}")
                    with archive.open(entry) as source, tempfile.TemporaryFile() as nested:
                        shutil.copyfileobj(source, nested, length=1024 * 1024)
                        nested.seek(0)
                        _zip(nested, f"{context}!{name}", depth + 1)
                elif name.lower().endswith(ARCHIVE_SUFFIXES):
                    raise ValueError(f"Cannot inspect unsupported nested archive: {context}: {name}")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError(f"Cannot inspect ZIP: {context}") from exc


def check(paths):
    for path in map(Path, paths):
        _check_name(str(path), path)
        if not path.exists():
            raise ValueError(f"Artifact does not exist: {path}")
        if path.is_symlink():
            raise ValueError(f"Cannot inspect symlink in distribution: {path}")
        if path.is_dir():
            check(path.iterdir())
        elif path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
            _zip(path, path)
        elif str(path).lower().endswith(ARCHIVE_SUFFIXES):
            raise ValueError(f"Cannot inspect unsupported archive: {path}")


def check_nsis(paths, seven_zip="7z"):
    for path in map(Path, paths):
        if not path.is_file():
            raise ValueError(f"Installer does not exist: {path}")
        try:
            result = subprocess.run(
                [seven_zip, "l", "-slt", "-sccUTF-8", "--", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise ValueError(f"Cannot inspect NSIS installer: {path}") from exc
        header, separator, inventory = result.stdout.partition("----------\n")
        names = [line.removeprefix("Path = ") for line in inventory.splitlines() if line.startswith("Path = ")]
        if result.returncode != 0 or "Type = Nsis" not in header.splitlines() or not separator or not names:
            raise ValueError(f"Cannot inspect NSIS installer: {path}")
        for name in names:
            _check_name(name, path)
            if name.lower().endswith(ARCHIVE_SUFFIXES):
                raise ValueError(f"Cannot inspect nested installer archive: {path}: {name}; audit an unpacked artifact instead")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--nsis", nargs="+", default=[])
    parser.add_argument("--seven-zip", default="7z")
    parser.add_argument("--allow-internal-links", action="store_true",
                        help="Linux onedir trees only: allow links to regular files within each root")
    args = parser.parse_args()
    if not args.paths and not args.nsis:
        parser.error("at least one artifact is required")
    try:
        if args.allow_internal_links:
            from linux_package import check_tree
            for path in args.paths:
                check_tree(path)
        else:
            check(args.paths)
        check_nsis(args.nsis, args.seven_zip)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"PASS: inspected {len(args.paths)} tree/ZIP input(s), {len(args.nsis)} NSIS installer(s)")
