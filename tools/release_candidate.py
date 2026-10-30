#!/usr/bin/env python3
"""Stage inspected build outputs and verify them before draft-release upload."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

REPOSITORY = "kein5/VRCT-VOX"
ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def identity(commit, version):
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not VERSION.fullmatch(version):
        raise ValueError("A full commit SHA and a single semantic version are required")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def names(platform, version, files):
    if platform == "windows":
        expected = {"VRCT-VOX.zip", "VRCT-VOX_cuda.zip", "VRCT-VOX_setup.exe"}
        if set(files) != expected:
            raise ValueError(
                "Windows candidate must include CPU/CUDA ZIPs and the stable setup asset"
            )
    elif platform == "linux":
        pattern = rf"VRCT-VOX-{re.escape(version)}-linux-x64-(?:cpu|vulkan)-release"
        if len(files) != 2 or not all(
            re.fullmatch(pattern + r"\.(?:tar\.gz|AppImage)", name) for name in files
        ):
            raise ValueError(
                "Linux candidate must include the versioned archive and AppImage"
            )
        if (
            len(
                {
                    name.removesuffix(".tar.gz").removesuffix(".AppImage")
                    for name in files
                }
            )
            != 1
        ):
            raise ValueError("Linux candidates must use the same engine variant")
    else:
        raise ValueError("Unsupported candidate platform")


def stage(output, assets, platform, commit, version):
    identity(commit, version)
    mapping = {}
    for asset in assets:
        if asset.is_symlink() or not asset.is_file() or asset.stat().st_size == 0:
            raise ValueError(f"Not a regular nonempty build output: {asset.name}")
        name = (
            "VRCT-VOX_setup.exe"
            if platform == "windows"
            and asset.name == f"VRCT-VOX_{version}_x64-setup.exe"
            else asset.name
        )
        if name in mapping:
            raise ValueError("Duplicate candidate asset")
        mapping[name] = asset
    names(platform, version, mapping)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for name, source in sorted(mapping.items()):
        destination = output / name
        shutil.copyfile(source, destination)
        entries.append(
            dict(name=name, size=destination.stat().st_size, sha256=digest(destination))
        )
        # NSIS reads exactly 64 ASCII bytes, without a trailing newline.
        (output / (name + ".sha256")).write_text(
            entries[-1]["sha256"], encoding="ascii"
        )
    manifest = dict(
        schema=1,
        repository=REPOSITORY,
        platform=platform,
        commit=commit,
        version=version,
        assets=entries,
    )
    (output / "candidate-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['name']}\n" for entry in entries),
        encoding="ascii",
    )
    return manifest


def verify(directory, platform, commit, version):
    identity(commit, version)
    manifest = json.loads(
        (directory / "candidate-manifest.json").read_text(encoding="utf-8")
    )
    for key, expected in dict(
        schema=1,
        repository=REPOSITORY,
        platform=platform,
        commit=commit,
        version=version,
    ).items():
        if manifest.get(key) != expected:
            raise ValueError(f"Candidate {key} mismatch")
    entries = manifest["assets"]
    filenames = [entry["name"] for entry in entries]
    if len(set(filenames)) != len(filenames) or any(
        Path(name).name != name or "/" in name or "\\" in name for name in filenames
    ):
        raise ValueError("Unsafe or duplicate candidate filenames")
    names(platform, version, filenames)
    if {path.name for path in directory.iterdir()} != set(filenames) | {
        name + ".sha256" for name in filenames
    } | {
        "candidate-manifest.json",
        "SHA256SUMS",
    }:
        raise ValueError("Unexpected candidate files")
    for entry in entries:
        path = directory / entry["name"]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size <= 0
            or path.stat().st_size != entry["size"]
            or digest(path) != entry["sha256"]
        ):
            raise ValueError(f"Candidate checksum mismatch: {entry['name']}")
        checksum = directory / (entry["name"] + ".sha256")
        if checksum.is_symlink() or checksum.read_bytes() != entry["sha256"].encode(
            "ascii"
        ):
            raise ValueError(f"Installer checksum sidecar mismatch: {entry['name']}")
    expected_sums = "".join(
        f"{entry['sha256']}  {entry['name']}\n" for entry in entries
    )
    if (directory / "SHA256SUMS").read_text(encoding="ascii") != expected_sums:
        raise ValueError("Checksum list mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["stage", "verify"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--platform", choices=["linux", "windows"], required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--version")
    parser.add_argument("--asset", type=Path, action="append", default=[])
    args = parser.parse_args()
    version = args.version or json.loads((ROOT / "package.json").read_text())["version"]
    if args.command == "stage":
        result = stage(args.directory, args.asset, args.platform, args.commit, version)
    else:
        result = verify(args.directory, args.platform, args.commit, version)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
