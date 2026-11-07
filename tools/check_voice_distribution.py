"""Reject OCR weights and private validation assets in fork distributions.

Inspect trees and ZIPs (including nested ZIPs). NSIS requires an explicit
--nsis and 7-Zip; unknown or nested installer containers fail closed. This is
a path inventory check, not detection of renamed weights hidden in binaries.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
import zipfile

try:
    from .distribution_policy import ARCHIVE_SUFFIXES, violation
except ImportError:
    from distribution_policy import ARCHIVE_SUFFIXES, violation

MAX_NESTED_ZIP = 128 * 1024 * 1024
MAX_INSPECTION_BYTES = 16 * 1024 * 1024 * 1024
MAX_INSPECTION_ENTRIES = 100_000
NSCURL_NOTICES = (
    "LICENSE.md", "LICENSE.brotli.md", "LICENSE.curl.md", "LICENSE.nghttp2.md",
    "LICENSE.openssl.md", "LICENSE.zlib.md", "LICENSE.zstd.md",
)


ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class _InspectionBudget:
    def __init__(self):
        self.bytes = MAX_INSPECTION_BYTES
        self.entries = MAX_INSPECTION_ENTRIES

    def consume(self, size, context):
        if size < 0 or size > self.bytes or self.entries < 1:
            raise ValueError(f"Cannot inspect archive within resource budget: {context}")
        self.bytes -= size
        self.entries -= 1


def _check_name(name, context):
    reason = violation(name)
    if reason:
        raise ValueError(f"{reason} in fork distribution: {context}: {name}")


def _inspect_member(source, size, name, context, depth, budget):
    # Read each member once, including renamed/preamble-prefixed ZIPs. Keep
    # large DLLs off disk: ZIP recognition only needs the end record/comment.
    with tempfile.TemporaryFile() as nested:
        total, signature, tail = 0, b"", b""
        while chunk := source.read(min(1024 * 1024, size - total + 1)):
            if not signature:
                signature = chunk[:4]
            total += len(chunk)
            if total > size:
                raise ValueError(f"Cannot inspect member with inconsistent size: {context}: {name}")
            if size <= MAX_NESTED_ZIP:
                nested.write(chunk)
            else:
                tail = (tail + chunk)[-(65535 + 22):]
        if total != size:
            raise ValueError(f"Cannot inspect truncated member: {context}: {name}")
        if size > MAX_NESTED_ZIP:
            nested.write(tail)
        nested.seek(0)
        if name.lower().endswith(".zip") or signature in ZIP_SIGNATURES or zipfile.is_zipfile(nested):
            if size > MAX_NESTED_ZIP:
                raise ValueError(f"Cannot inspect oversized nested ZIP: {context}: {name}")
            nested.seek(0)
            _zip(nested, f"{context}!{name}", depth + 1, prefix=name, budget=budget)
        elif name.lower().endswith(ARCHIVE_SUFFIXES):
            raise ValueError(f"Cannot inspect unsupported nested archive: {context}: {name}")


def _zip(stream, context, depth=0, *, prefix="", budget=None):
    if depth > 4:
        raise ValueError(f"Cannot inspect excessive ZIP nesting: {context}")
    if budget is None:
        budget = _InspectionBudget()
    try:
        with zipfile.ZipFile(stream) as archive:
            for entry in archive.infolist():
                name = f"{prefix}/{entry.filename}" if prefix else entry.filename
                budget.consume(entry.file_size, context)
                _check_name(name, context)
                if entry.flag_bits & 1:
                    raise ValueError(f"Cannot inspect encrypted ZIP: {context}")
                if entry.is_dir():
                    continue
                with archive.open(entry) as source:
                    _inspect_member(source, entry.file_size, name, context, depth, budget)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError(f"Cannot inspect ZIP: {context}") from exc


def check(paths, *, root=None):
    for path in map(Path, paths):
        artifact_root = Path(root) if root is not None else (path if path.is_dir() else path.parent)
        name = path.relative_to(artifact_root).as_posix()
        _check_name(name, path)
        if not path.exists():
            raise ValueError(f"Artifact does not exist: {path}")
        if path.is_symlink():
            raise ValueError(f"Cannot inspect symlink in distribution: {path}")
        if path.is_dir():
            check(path.iterdir(), root=artifact_root)
        elif path.suffix.lower() == ".zip" or zipfile.is_zipfile(path):
            _zip(path, path, prefix=name)
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
        normalized = {name.replace("\\", "/").lower() for name in names}
        for notice in NSCURL_NOTICES:
            required = "licenses/nscurl/" + notice.lower()
            if not any(name == required or name.endswith("/" + required) for name in normalized):
                raise ValueError(f"Missing NScurl notice in NSIS installer: {path}: {notice}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--nsis", nargs="+", default=[])
    parser.add_argument("--seven-zip", default="7z")
    parser.add_argument("--allow-internal-links", action="store_true",
                        help="Linux onedir trees only: allow links to regular files within each root")
    parser.add_argument("--windows-voice", metavar="INTERNAL",
                        help="also require the speech engine, voice workers and notices in this _internal tree")
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
        if args.windows_voice:
            from windows_voice_resources import missing_files
            if missing := missing_files(args.windows_voice):
                raise ValueError(f"Missing from the Windows build: {', '.join(missing)}")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"PASS: inspected {len(args.paths)} tree/ZIP input(s), {len(args.nsis)} NSIS installer(s)")
