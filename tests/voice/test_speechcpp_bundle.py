"""Bundle only verified executables and attribution; never arbitrary ZIP paths."""

import copy
from contextlib import nullcontext
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
LICENSE_NAMES = {
    "NOTICE.md",
    "speech.cpp-LICENSE",
    "ggml-LICENSE",
    "cpp-httplib-LICENSE",
    "miniaudio-LICENSE",
    "GCC-COPYING3",
    "GCC-COPYING.RUNTIME",
}


def module():
    return importlib.import_module("tools.speechcpp_bundle")


def archive(tmp_path, *, entries=None):
    m = module()
    target = tmp_path / "release.zip"
    with zipfile.ZipFile(target, "w") as out:
        for name, value in entries or [
            ("speech", b"fake executable"),
            ("unwanted.gguf", b"private"),
            ("../escape", b"no"),
            ("libspeech.so", b"not needed"),
        ]:
            out.writestr(name, value)
    asset = copy.deepcopy(m.load_manifest()["assets"]["linux-x64-cpu"])
    asset["size"] = target.stat().st_size
    asset["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return target, asset


def test_staged_inventory_has_only_executable_and_all_pinned_notices(tmp_path):
    m = module()
    source, asset = archive(tmp_path)
    output = tmp_path / "bundle"
    result = m.stage_bundle(source, output, asset)
    assert {
        p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()
    } == {"speech", "bundle.json", *{"notices/" + n for n in LICENSE_NAMES}}
    assert (output / "speech").read_bytes() == b"fake executable"
    assert os.access(output / "speech", os.X_OK)
    assert not (tmp_path / "escape").exists()
    assert result["archive"]["sha256"] == asset["sha256"]
    assert result["variant"] == "linux-x64-cpu"
    assert (
        m.verify_bundle(output)
        == result
        == json.loads((output / "bundle.json").read_text())
    )
    for row in result["files"]:
        assert (
            hashlib.sha256((output / row["path"]).read_bytes()).hexdigest()
            == row["sha256"]
        )


@pytest.mark.parametrize("mutation", ["same_size", "short", "long"])
def test_corrupt_archive_cannot_create_bundle(tmp_path, mutation):
    m = module()
    source, asset = archive(tmp_path)
    body = source.read_bytes()
    source.write_bytes(
        {"same_size": b"x" + body[1:], "short": body[:-1], "long": body + b"x"}[
            mutation
        ]
    )
    with pytest.raises(ValueError, match="speech_bundle_(hash|size)"):
        m.stage_bundle(source, tmp_path / "bundle", asset)
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("fault", ["duplicate", "symlink", "missing", "directory"])
def test_invalid_executable_entry_rejected_without_extracting(tmp_path, fault):
    entry = zipfile.ZipInfo("speech")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    entries = {
        "duplicate": [("speech", b"one"), ("speech", b"two")],
        "symlink": [(entry, b"/bin/sh")],
        "missing": [("else", b"no")],
        "directory": [("speech/", b"")],
    }[fault]
    with pytest.warns(UserWarning) if fault == "duplicate" else nullcontext():
        source, asset = archive(tmp_path, entries=entries)
    with pytest.raises(ValueError, match="speech_bundle_executable"):
        module().stage_bundle(source, tmp_path / "bundle", asset)
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_existing_output_is_never_overwritten(tmp_path, kind):
    m = module()
    source, asset = archive(tmp_path)
    output = tmp_path / "bundle"
    original = tmp_path / "original"
    original.write_bytes(b"keep")
    if kind == "file":
        output.write_bytes(b"keep")
    elif kind == "directory":
        output.mkdir()
        (output / "precious").write_bytes(b"keep")
    else:
        output.symlink_to(original)
    with pytest.raises((ValueError, FileExistsError)):
        m.stage_bundle(source, output, asset)
    assert original.read_bytes() == b"keep"
    assert (
        output / "precious" if kind == "directory" else output
    ).read_bytes() == b"keep"
    assert output.is_symlink() == (kind == "symlink")


@pytest.mark.parametrize("fault", ["missing", "corrupt", "symlink"])
def test_bad_notices_reject_staging(tmp_path, fault):
    m = module()
    source, asset = archive(tmp_path)
    notice_root = tmp_path / "notices"
    shutil.copytree(m.NOTICES, notice_root)
    target = notice_root / "GCC-COPYING.RUNTIME"
    if fault == "corrupt":
        target.write_bytes(b"changed")
    else:
        target.unlink()
        if fault == "symlink":
            target.symlink_to(m.NOTICES / "GCC-COPYING.RUNTIME")
    with pytest.raises(ValueError, match="speech_bundle_"):
        m.stage_bundle(source, tmp_path / "bundle", asset, notice_root=notice_root)
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize(
    "member", ["speech", "notices/NOTICE.md", "notices/GCC-COPYING3"]
)
def test_verify_rejects_tampering_after_staging(tmp_path, member):
    m = module()
    source, asset = archive(tmp_path)
    output = tmp_path / "bundle"
    m.stage_bundle(source, output, asset)
    (output / member).write_bytes(b"changed")
    with pytest.raises(ValueError, match="speech_bundle_"):
        m.verify_bundle(output)


def test_verify_rejects_unlisted_private_file(tmp_path):
    m = module()
    source, asset = archive(tmp_path)
    output = tmp_path / "bundle"
    m.stage_bundle(source, output, asset)
    (output / "Mia2026.pth").write_bytes(b"must not ship")
    with pytest.raises(ValueError, match="speech_bundle_inventory"):
        m.verify_bundle(output)


@pytest.mark.parametrize("body", [b"good", b"evil", b"short", b"good extra"])
def test_downloader_verifies_exact_bytes_before_completion(tmp_path, body):
    m = module()
    asset = copy.deepcopy(m.load_manifest()["assets"]["linux-x64-cpu"])
    asset.update(size=4, sha256=hashlib.sha256(b"good").hexdigest())
    calls = []

    def opener(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(body)

    dest = tmp_path / "archive.zip"
    if body == b"good":
        assert m.fetch_archive(asset, dest, opener=opener) == dest
        assert dest.read_bytes() == b"good"
    else:
        with pytest.raises(ValueError, match="speech_bundle_(hash|size)"):
            m.fetch_archive(asset, dest, opener=opener)
        assert not dest.exists()
    assert (
        calls[0][0]
        == "https://github.com/nyosegawa/speech.cpp/releases/download/v0.9.0/speech-0.9.0-linux-x64-cpu.zip"
    )
    assert not list(tmp_path.glob("*.part"))


def test_interrupted_download_and_existing_destination_are_preserved(tmp_path):
    m = module()
    asset = m.load_manifest()["assets"]["linux-x64-cpu"]

    class Broken(io.BytesIO):
        def read(self, count):
            raise OSError("interrupted")

    dest = tmp_path / "release.zip"
    with pytest.raises(OSError):
        m.fetch_archive(asset, dest, opener=lambda *a, **kw: Broken())
    assert not list(tmp_path.iterdir())
    dest.write_bytes(b"keep")

    def forbidden(*a, **kw):
        pytest.fail("must reject existing target before network")

    with pytest.raises((ValueError, FileExistsError)):
        m.fetch_archive(asset, dest, opener=forbidden)
    assert dest.read_bytes() == b"keep"


def test_cli_local_archive_does_not_access_network(tmp_path, monkeypatch):
    m = module()
    source, asset = archive(tmp_path)
    manifest = m.load_manifest()
    manifest["assets"]["linux-x64-cpu"] = asset
    monkeypatch.setattr(m, "load_manifest", lambda *a, **kw: manifest)
    monkeypatch.setattr(
        m, "fetch_archive", lambda *a, **kw: pytest.fail("unexpected network")
    )
    m.main(
        [
            "--variant",
            "linux-x64-cpu",
            "--archive",
            str(source),
            "--output",
            str(tmp_path / "bundle"),
        ]
    )
    assert m.verify_bundle(tmp_path / "bundle")["variant"] == "linux-x64-cpu"


def test_cli_requires_explicit_source_choice(tmp_path):
    with pytest.raises(SystemExit) as exc:
        module().main(
            ["--variant", "linux-x64-cpu", "--output", str(tmp_path / "bundle")]
        )
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


def test_optimized_python_still_rejects_invalid_release(tmp_path):
    source, asset = archive(tmp_path)
    source.write_bytes(b"corrupt")
    request = tmp_path / "request.json"
    request.write_text(json.dumps(asset))
    script = (
        "import json,sys; from pathlib import Path; from tools.speechcpp_bundle import stage_bundle; "
        "stage_bundle(Path(sys.argv[1]),Path(sys.argv[2]),json.loads(Path(sys.argv[3]).read_text()))"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            script,
            str(source),
            str(tmp_path / "bundle"),
            str(request),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "speech_bundle_size" in result.stderr
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize(
    "fault", ["schema", "url", "size", "digest", "notice_path", "duplicate_notice"]
)
def test_invalid_manifest_rejected_before_work(tmp_path, fault):
    m = module()
    manifest = m.load_manifest()
    if fault == "schema":
        manifest["schema"] = True
    elif fault == "url":
        manifest["assets"]["linux-x64-cpu"]["url"] = "https://example.org/model.gguf"
    elif fault == "size":
        manifest["assets"]["linux-x64-cpu"]["size"] = True
    elif fault == "digest":
        manifest["assets"]["linux-x64-cpu"]["sha256"] = "no"
    elif fault == "notice_path":
        manifest["notices"][0]["path"] = "../escape"
    else:
        manifest["notices"].append(copy.deepcopy(manifest["notices"][0]))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="speech_bundle_manifest"):
        m.load_manifest(path)


def test_download_refuses_unreviewed_url_before_network(tmp_path):
    m = module()
    asset = copy.deepcopy(m.load_manifest()["assets"]["linux-x64-cpu"])
    asset["url"] = "https://example.org/anything"

    def forbidden(*a, **kw):
        pytest.fail("unreviewed URL reached network")

    with pytest.raises(ValueError, match="speech_bundle_manifest"):
        m.fetch_archive(asset, tmp_path / "archive", opener=forbidden)
    assert not list(tmp_path.iterdir())


def test_archive_replacement_after_validation_cannot_change_staged_bytes(
    tmp_path, monkeypatch
):
    m = module()
    source, asset = archive(tmp_path)
    replacement = tmp_path / "replacement.zip"
    with zipfile.ZipFile(replacement, "w") as out:
        out.writestr("speech", b"unverified executable")
    real_zip = zipfile.ZipFile

    def replace_before_open(*args, **kwargs):
        shutil.copyfile(replacement, source)
        return real_zip(*args, **kwargs)

    monkeypatch.setattr(m.zipfile, "ZipFile", replace_before_open)
    m.stage_bundle(source, tmp_path / "bundle", asset)
    assert (tmp_path / "bundle/speech").read_bytes() == b"fake executable"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Linux special-file rejection")
def test_special_metadata_is_rejected_instead_of_blocking(tmp_path):
    m = module()
    source, asset = archive(tmp_path)
    output = tmp_path / "bundle"
    m.stage_bundle(source, output, asset)
    (output / "bundle.json").unlink()
    os.mkfifo(output / "bundle.json")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from tools.speechcpp_bundle import verify_bundle; verify_bundle(sys.argv[1])",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode != 0 and "speech_bundle_inventory" in result.stderr
