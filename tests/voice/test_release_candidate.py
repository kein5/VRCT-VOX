import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.release_candidate import stage, verify
from tools.prepare_release import check_run, prepare, release_channel, require_unused_tag

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
        if argv[:3] == ["gh", "attestation", "verify"]:
            return
        shutil.copytree(candidate, argv[argv.index("--dir") + 1])

    monkeypatch.setattr(subprocess, "run", download)
    payload = prepare(tmp_path / "draft", {"windows": "123"}, SHA, VERSION, "develop")
    for name in ("VRCT-VOX.zip", "VRCT-VOX_cuda.zip", "VRCT-VOX_setup.exe"):
        assert (payload / (name + ".sha256")).read_bytes() == (
            candidate / (name + ".sha256")
        ).read_bytes()
        assert len((payload / (name + ".sha256")).read_bytes()) == 64


def _draft(candidate, tmp_path, monkeypatch, attestation):
    run = dict(
        conclusion="success", status="completed", event="workflow_dispatch", head_branch="develop",
        head_sha=SHA, path=".github/workflows/release.yml",
        repository={"full_name": "kein5/VRCT-VOX"}, head_repository={"full_name": "kein5/VRCT-VOX"},
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: json.dumps(run))
    checked = []

    def fake_run(argv, **kwargs):
        if argv[:3] == ["gh", "attestation", "verify"]:
            checked.append(argv)
            attestation(argv)
            return
        shutil.copytree(candidate, argv[argv.index("--dir") + 1])

    monkeypatch.setattr(subprocess, "run", fake_run)
    return checked, lambda: prepare(tmp_path / "draft", {"windows": "123"}, SHA, VERSION, "develop")


def test_every_candidate_file_needs_provenance_from_its_workflow_and_commit(candidate, tmp_path, monkeypatch):
    """Second security audit SEC-04: signed build provenance, not only checksums."""
    checked, run_prepare = _draft(candidate, tmp_path, monkeypatch, lambda argv: None)
    payload = run_prepare()
    files = sorted(path.name for path in candidate.iterdir())
    assert sorted(Path(argv[3]).name for argv in checked) == files
    for argv in checked:
        options = dict(zip(argv[4::2], argv[5::2]))
        assert options["--repo"] == "kein5/VRCT-VOX"
        assert options["--signer-workflow"] == "kein5/VRCT-VOX/.github/workflows/release.yml"
        assert options["--source-digest"] == SHA
        assert options["--source-ref"] == "refs/heads/develop"
        assert "--deny-self-hosted-runners" in argv
    assert (payload / "VRCT-VOX.zip").is_file()


def test_a_file_without_valid_provenance_stops_the_draft(candidate, tmp_path, monkeypatch):
    def refuse(argv):
        if argv[3].endswith("VRCT-VOX_cuda.zip"):
            raise subprocess.CalledProcessError(1, argv, stderr="no attestations found")

    _, run_prepare = _draft(candidate, tmp_path, monkeypatch, refuse)
    with pytest.raises(subprocess.CalledProcessError):
        run_prepare()
    assert not any((tmp_path / "draft" / "payload").iterdir())

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


def _linux_assets(tmp_path, suffixes):
    assets = []
    for suffix in suffixes:
        path = tmp_path / f"VRCT-VOX-{VERSION}-linux-x64-{suffix}"
        path.write_bytes(b"candidate")
        assets.append(path)
    return assets


def test_linux_candidate_carries_archive_appimage_deb_and_rpm(tmp_path):
    assets = _linux_assets(tmp_path, ("vulkan-release.tar.gz", "vulkan-release.AppImage",
                                      "vulkan-release.deb", "vulkan-release.rpm"))
    stage(tmp_path / "out", assets, "linux", SHA, VERSION)
    names = {entry["name"] for entry in verify(tmp_path / "out", "linux", SHA, VERSION)["assets"]}
    assert {name.rsplit(".", 1)[-1] for name in names} == {"gz", "AppImage", "deb", "rpm"}


def test_linux_candidate_without_its_packages_is_refused(tmp_path):
    assets = _linux_assets(tmp_path, ("vulkan-release.tar.gz", "vulkan-release.AppImage"))
    with pytest.raises(ValueError, match="deb and rpm"):
        stage(tmp_path / "out", assets, "linux", SHA, VERSION)


def test_linux_variant_pair_required(tmp_path):
    assets = _linux_assets(tmp_path, ("vulkan-release.AppImage", "cpu-release.tar.gz",
                                      "vulkan-release.deb", "vulkan-release.rpm"))
    with pytest.raises(ValueError, match="same engine"):
        stage(tmp_path / "out", assets, "linux", SHA, VERSION)


def test_linux_candidate_needs_one_of_each_format(tmp_path):
    assets = _linux_assets(tmp_path, ("vulkan-release.tar.gz", "vulkan-release.AppImage",
                                      "vulkan-release.deb", "cpu-release.deb"))
    with pytest.raises(ValueError):
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
        check_run(run, "linux", SHA, "develop")
    else:
        run[mutation] = (
            {"full_name": "someone/fork"}
            if mutation == "head_repository"
            else "untrusted"
        )
        with pytest.raises(ValueError):
            check_run(run, "linux", SHA, "develop")


@pytest.mark.parametrize("branch,version,channel", [
    ("main", "0.1.0", "stable"),
    ("main", "12.0.3", "stable"),
    ("develop", "0.2.0-beta.1", "beta"),
    ("develop", "1.0.0-beta.12", "beta"),
])
def test_main_releases_stable_and_develop_releases_betas(branch, version, channel):
    assert release_channel(branch, version) == channel


@pytest.mark.parametrize("branch,version", [
    ("main", "0.1.0-beta.1"),      # A beta must not be published from main.
    ("develop", "0.1.0"),          # A stable version must not come from develop.
    ("develop", "0.1.0-rc.1"),
    ("develop", "0.1.0-beta.0"),
    ("main", "01.0.0"),
    ("feature/x", "0.1.0"),
])
def test_branch_and_version_must_agree(branch, version):
    with pytest.raises(ValueError):
        release_channel(branch, version)


def test_candidate_from_another_branch_is_rejected():
    run = dict(conclusion="success", status="completed", event="workflow_dispatch",
               head_branch="develop", head_sha=SHA, path=".github/workflows/build-linux.yml",
               repository={"full_name": "kein5/VRCT-VOX"}, head_repository={"full_name": "kein5/VRCT-VOX"})
    with pytest.raises(ValueError):
        check_run(run, "linux", SHA, "main")
