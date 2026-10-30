import json
import shutil
import subprocess

import pytest

from tools.release_candidate import stage, verify
from tools.prepare_release import check_run, prepare, require_unused_tag

SHA = "a" * 40
VERSION = "3.6.0-beta.1"


@pytest.fixture
def candidate(tmp_path):
    assets = []
    for name in (
        "VRCT-VOX.zip",
        "VRCT-VOX_cuda.zip",
        f"VRCT-VOX_{VERSION}_x64-setup.exe",
    ):
        path = tmp_path / name
        path.write_bytes(b"inspected synthetic output")
        assets.append(path)
    output = tmp_path / "candidate"
    stage(output, assets, "windows", SHA, VERSION)
    return output


def test_stage_alias_and_verify(candidate):
    result = verify(candidate, "windows", SHA, VERSION)
    assert "VRCT-VOX_setup.exe" in {entry["name"] for entry in result["assets"]}
    for entry in result["assets"]:
        assert (candidate / (entry["name"] + ".sha256")).read_bytes() == entry[
            "sha256"
        ].encode("ascii")


def test_prepare_preserves_installer_checksums(candidate, tmp_path, monkeypatch):
    run = dict(
        conclusion="success",
        status="completed",
        event="workflow_dispatch",
        head_branch="develop",
        head_sha=SHA,
        path=".github/workflows/release.yml",
        repository={"full_name": "kein5/VRCT-VOX"},
        head_repository={"full_name": "kein5/VRCT-VOX"},
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: json.dumps(run))

    def download(argv, **_kwargs):
        shutil.copytree(candidate, argv[argv.index("--dir") + 1])

    monkeypatch.setattr(subprocess, "run", download)
    payload = prepare(tmp_path / "draft", {"windows": "123"}, SHA, VERSION)
    for name in ("VRCT-VOX.zip", "VRCT-VOX_cuda.zip", "VRCT-VOX_setup.exe"):
        assert (payload / (name + ".sha256")).read_bytes() == (
            candidate / (name + ".sha256")
        ).read_bytes()
        assert len((payload / (name + ".sha256")).read_bytes()) == 64


def test_checksum_newline_is_rejected(candidate):
    path = candidate / "VRCT-VOX.zip.sha256"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="sidecar"):
        verify(candidate, "windows", SHA, VERSION)


@pytest.mark.parametrize(
    "kind", ["absent", "lightweight", "annotated", "error", "malformed"]
)
def test_existing_tags_or_lookup_failure_never_mean_tag_absent(kind, monkeypatch):
    def lookup(argv, **_kwargs):
        assert "--paginate" in argv and "--slurp" in argv
        if kind == "error":
            raise subprocess.CalledProcessError(1, argv, stderr="HTTP 404")
        if kind == "malformed":
            return "{}"
        if kind == "absent":
            return "[[]]"
        return json.dumps(
            [
                [
                    {
                        "ref": "refs/tags/v" + VERSION,
                        "object": {
                            "type": "tag" if kind == "annotated" else "commit",
                            "sha": "b" * 40,
                        },
                    }
                ]
            ]
        )

    monkeypatch.setattr(subprocess, "check_output", lookup)
    if kind == "absent":
        require_unused_tag(VERSION)
    else:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            require_unused_tag(VERSION)


@pytest.mark.parametrize(
    "mutation",
    ["bytes", "commit", "version", "repository", "path", "extra", "checksums"],
)
def test_rejects_modified_or_misidentified_candidate(candidate, mutation):
    path = candidate / "candidate-manifest.json"
    data = json.loads(path.read_text())
    if mutation == "bytes":
        (candidate / "VRCT-VOX.zip").write_bytes(b"tampered")
    elif mutation in ("commit", "version", "repository"):
        data[mutation] = "unexpected"
    elif mutation == "path":
        data["assets"][0]["name"] = "../VRCT-VOX.zip"
    elif mutation == "extra":
        (candidate / "private.log").write_text("must not publish")
    elif mutation == "checksums":
        (candidate / "SHA256SUMS").write_text("incorrect")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify(candidate, "windows", SHA, VERSION)


def test_linux_variant_pair_required(tmp_path):
    assets = []
    for suffix in ("vulkan-release.AppImage", "cpu-release.tar.gz"):
        path = tmp_path / f"VRCT-VOX-{VERSION}-linux-x64-{suffix}"
        path.write_bytes(b"candidate")
        assets.append(path)
    with pytest.raises(ValueError, match="same engine"):
        stage(tmp_path / "out", assets, "linux", SHA, VERSION)


@pytest.mark.parametrize(
    "mutation",
    [None, "event", "conclusion", "head_sha", "head_branch", "path", "head_repository"],
)
def test_release_draft_only_accepts_successful_canonical_manual_builds(mutation):
    run = dict(
        conclusion="success",
        status="completed",
        event="workflow_dispatch",
        head_branch="develop",
        head_sha=SHA,
        path=".github/workflows/build-linux.yml",
        repository={"full_name": "kein5/VRCT-VOX"},
        head_repository={"full_name": "kein5/VRCT-VOX"},
    )
    if mutation is None:
        check_run(run, "linux", SHA)
    else:
        run[mutation] = (
            {"full_name": "someone/fork"}
            if mutation == "head_repository"
            else "untrusted"
        )
        with pytest.raises(ValueError):
            check_run(run, "linux", SHA)
