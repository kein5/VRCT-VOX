"""Download successful manual candidates at this commit; prepare a release draft."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote

from tools.release_candidate import REPOSITORY, ROOT, verify

WORKFLOWS = {"linux": "build-linux.yml", "windows": "release.yml"}
# main publishes stable releases; develop publishes betas (GitHub prereleases).
CHANNELS = {
    "main": ("stable", r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"),
    "develop": ("beta", r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-beta\.[1-9][0-9]*"),
}


def release_channel(branch, version):
    """The channel of a release from `branch`; its version must match it."""
    if branch not in CHANNELS:
        raise ValueError("Releases are made only from main (stable) or develop (beta)")
    channel, pattern = CHANNELS[branch]
    if not isinstance(version, str) or not re.fullmatch(pattern, version):
        raise ValueError(
            "main releases need a version X.Y.Z and develop releases X.Y.Z-beta.N"
        )
    return channel


def check_run(run, platform, commit, branch):
    expected = dict(
        conclusion="success",
        status="completed",
        event="workflow_dispatch",
        head_branch=branch,
        head_sha=commit,
        path=f".github/workflows/{WORKFLOWS[platform]}",
    )
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "Candidate must be a successful manual build of the release branch at the requested commit"
        )
    if any(
        run.get(key, {}).get("full_name") != REPOSITORY
        for key in ("repository", "head_repository")
    ):
        raise ValueError("Candidate must originate in the canonical repository")


def prepare(output, run_ids, commit, version, branch):
    # Never execute downloaded code. Only allowlisted files from verified runs
    # are copied to the draft payload; candidate integrity is a hard failure.
    release_channel(branch, version)
    output.mkdir(parents=True, exist_ok=False)
    payload = output / "payload"
    payload.mkdir()
    for platform, run_id in run_ids.items():
        if not re.fullmatch(r"[1-9][0-9]*", run_id):
            raise ValueError("A numeric workflow run ID is required")
        raw = subprocess.check_output(
            ["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}"], text=True
        )
        run = json.loads(raw)
        check_run(run, platform, commit, branch)
        directory = output / platform
        artifact = (
            "VRCT-VOX-linux-x86_64-candidate"
            if platform == "linux"
            else "VRCT-VOX-windows-candidate"
        )
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                REPOSITORY,
                "--name",
                artifact,
                "--dir",
                str(directory),
            ],
            check=True,
        )
        manifest = verify(directory, platform, commit, version)
        for entry in manifest["assets"]:
            destination = payload / entry["name"]
            if destination.exists():
                raise ValueError("Overlapping candidate names")
            shutil.copyfile(directory / entry["name"], destination)
            shutil.copyfile(
                directory / (entry["name"] + ".sha256"),
                payload / (entry["name"] + ".sha256"),
            )
        shutil.copyfile(
            directory / "candidate-manifest.json",
            payload / f"candidate-{platform}.json",
        )
        shutil.copyfile(directory / "SHA256SUMS", payload / f"SHA256SUMS-{platform}")
    return payload


def require_unused_tag(version):
    """Reject existing tags, including annotated tags, without changing any ref."""
    endpoint = f"repos/{REPOSITORY}/git/matching-refs/tags/" + quote(
        "v" + version, safe=""
    )
    # Successful empty matches are the only absence signal. HTTP, permission,
    # authentication and network errors all propagate as failures.
    pages = json.loads(
        subprocess.check_output(
            ["gh", "api", endpoint, "--paginate", "--slurp"], text=True
        )
    )
    if (
        not isinstance(pages, list)
        or not pages
        or any(not isinstance(page, list) for page in pages)
    ):
        raise ValueError("Unexpected GitHub tag lookup response")
    for page in pages:
        for ref in page:
            if not isinstance(ref, dict) or not isinstance(ref.get("ref"), str):
                raise ValueError("Unexpected GitHub tag record")
            if ref["ref"] == "refs/tags/v" + version:
                raise ValueError(
                    "Release tag already exists; choose a new version instead of retargeting it"
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-run", required=True)
    parser.add_argument("--windows-run", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--branch", required=True, choices=sorted(CHANNELS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = json.loads((ROOT / "package.json").read_text())["version"]
    payload = prepare(
        args.output,
        {"linux": args.linux_run, "windows": args.windows_run},
        args.commit,
        version,
        args.branch,
    )
    print(f"Verified draft assets: {payload}")


if __name__ == "__main__":
    main()
