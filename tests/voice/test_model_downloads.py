"""No network, Torch, model loading or audio: exercise the real file transaction."""

from dataclasses import replace
import hashlib
import io
from pathlib import Path
from threading import Event
import time

import pytest


@pytest.fixture
def setup(tmp_path):
    assert (
        Path(__file__).resolve().parents[2]
        / "src-python/models/model_downloads/manager.py"
    ).is_file(), "download manager not implemented"
    from models.model_downloads.catalog import Artifact, Model
    from models.model_downloads.manager import Downloads

    content = b"GGUF" + b"example tensor bytes" * 4
    artifact = Artifact(
        "model.gguf", len(content), hashlib.sha256(content).hexdigest(), "model"
    )
    entry = Model(
        "test-model",
        "japanese",
        "Test",
        "Author",
        "author/model",
        "a" * 40,
        "MIT",
        ("https://huggingface.co/author/model/blob/" + "a" * 40 + "/LICENSE",),
        "irodori",
        (artifact,),
    )
    opened = []

    def transport(url):
        opened.append(url)
        return io.BytesIO(content)

    manager = Downloads(
        tmp_path / "models", catalog=(entry,), transport=transport, reserve_bytes=0
    )
    yield manager, entry, content, opened
    manager.close()


def finish(manager):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        state = manager.state()["jobs"].get("test-model", {})
        if state.get("phase") in ("ready", "failed", "cancelled", "applied"):
            return state
        time.sleep(0.005)
    raise AssertionError(manager.state())


def start(manager, **overrides):
    return manager.start(
        {
            "id": "test-model",
            "consent": True,
            "catalog_version": manager.catalog_version,
            **overrides,
        }
    )


@pytest.mark.parametrize("consent", [False, 1, "yes", None])
def test_explicit_consent_before_any_files_or_network(setup, consent):
    m, _, _, opened = setup
    assert m.state()["jobs"] == {} and m.catalog()["models"]
    with pytest.raises(ValueError, match="consent_required"):
        start(m, consent=consent)
    assert not opened and not m.root.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "../outside"},
        {"catalog_version": "stale"},
        {"url": "https://elsewhere/model"},
    ],
)
def test_only_fixed_catalog_requests_are_accepted(setup, overrides):
    m, _, _, opened = setup
    with pytest.raises(ValueError):
        start(m, **overrides)
    assert not opened


def test_verified_completion_does_not_apply_or_load_and_can_be_applied_explicitly(
    setup,
):
    m, entry, content, opened = setup
    start(m)
    job = finish(m)
    assert job["phase"] == "ready" and job["received_bytes"] == len(content)
    target = Path(job["paths"]["model"])
    assert target.read_bytes() == content
    assert opened == [
        f"https://huggingface.co/{entry.repo}/resolve/{entry.revision}/model.gguf"
    ]
    applied = []
    m.apply(entry.id, job["job_id"], lambda e, paths: applied.append(paths))
    assert applied == [{"model": str(target)}]
    assert m.state()["jobs"][entry.id]["phase"] == "applied"


@pytest.mark.parametrize(
    "data,code",
    [
        (b"GGUFwrong", "size_mismatch"),
        (b"x" * 200, "size_mismatch"),
        (None, "hash_mismatch"),
    ],
)
def test_incomplete_oversized_or_corrupt_download_never_publishes(setup, data, code):
    m, _, content, _ = setup
    m.transport = lambda _: io.BytesIO(
        data if data is not None else b"x" * len(content)
    )
    start(m)
    job = finish(m)
    assert job["phase"] == "failed" and job["error_code"] == code
    assert not job["paths"] and not list(m.root.rglob("*.gguf"))
    assert not list(m.root.glob(".partial-*"))


def test_cancel_keeps_no_partial_path_and_old_job_cannot_cancel_retry(setup):
    m, entry, content, _ = setup
    entered, release = Event(), Event()

    class Slow(io.BytesIO):
        def read(self, n=-1):
            entered.set()
            assert release.wait(2)
            return super().read(n)

    m.transport = lambda _: Slow(content)
    start(m)
    assert entered.wait(1)
    job = m.state()["jobs"][entry.id]
    m.cancel(entry.id, job["job_id"])
    release.set()
    assert finish(m)["phase"] == "cancelled"
    assert not list(m.root.rglob("*.gguf"))
    m.transport = lambda _: io.BytesIO(content)
    start(m)
    retry = finish(m)
    assert retry["phase"] == "ready"
    with pytest.raises(ValueError, match="stale_job"):
        m.cancel(entry.id, job["job_id"])
    assert m.state()["jobs"][entry.id]["job_id"] == retry["job_id"]


def test_disk_preflight_fails_without_network(setup, monkeypatch):
    import shutil

    m, _, _, opened = setup
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: type("Usage", (), {"free": 0})()
    )
    start(m)
    job = finish(m)
    assert job["phase"] == "failed" and job["error_code"] == "insufficient_space"
    assert not opened


def test_disk_full_during_write_leaves_no_selectable_file(setup, monkeypatch):
    import errno
    import os

    m, _, _, _ = setup
    calls = 0
    real = os.fsync

    def full(fd):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError(errno.ENOSPC, "full")
        return real(fd)

    monkeypatch.setattr(os, "fsync", full)
    start(m)
    job = finish(m)
    assert job["phase"] == "failed" and job["error_code"] == "insufficient_space"
    assert not job["paths"] and not list(m.root.rglob("*.gguf"))


def test_network_failure_removes_staging_and_preserves_unrelated_files(setup):
    m, _, _, _ = setup
    m.root.mkdir()
    unrelated = m.root / "user.pth"
    unrelated.write_bytes(b"user model")

    def fail(_):
        raise OSError("network private details")

    m.transport = fail
    start(m)
    job = finish(m)
    assert job["phase"] == "failed" and job["error_code"] == "download_failed"
    assert unrelated.read_bytes() == b"user model"
    assert not list(m.root.glob(".partial-*"))


def test_complete_cache_is_reverified_and_corrupt_cache_is_preserved(setup):
    m, _, content, opened = setup
    start(m)
    path = Path(finish(m)["paths"]["model"])
    start(m)
    assert finish(m)["phase"] == "ready" and len(opened) == 1
    path.write_bytes(b"bad cache")
    start(m)
    assert finish(m)["phase"] == "failed"
    assert path.read_bytes() == b"bad cache" and len(opened) == 1


def test_symlink_destination_cannot_overwrite_outside_file(setup, tmp_path):
    m, entry, _, opened = setup
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath("model.gguf").write_bytes(b"do not change")
    m.root.mkdir()
    (m.root / entry.id).symlink_to(outside, target_is_directory=True)
    start(m)
    assert finish(m)["phase"] == "failed"
    assert (
        outside.joinpath("model.gguf").read_bytes() == b"do not change" and not opened
    )


def test_tampered_file_cannot_be_applied(setup):
    m, entry, _, _ = setup
    start(m)
    job = finish(m)
    Path(job["paths"]["model"]).write_bytes(b"changed")
    with pytest.raises(ValueError):
        m.apply(entry.id, job["job_id"], lambda *_: pytest.fail("applied corrupt data"))


def test_failed_setting_application_keeps_download_available(setup):
    m, entry, _, _ = setup
    start(m)
    job = finish(m)

    def refuse(*_):
        raise ValueError("settings_changed")

    with pytest.raises(ValueError, match="settings_changed"):
        m.apply(entry.id, job["job_id"], refuse)
    assert m.state()["jobs"][entry.id]["phase"] == "ready"


def test_close_prohibits_future_network_or_apply(setup):
    m, _, _, opened = setup
    assert m.close()
    with pytest.raises(ValueError, match="downloads_closed"):
        start(m)
    assert not opened


def test_unexpected_stream_error_is_a_failure_not_a_stuck_job(setup):
    from http.client import IncompleteRead

    m, _, _, _ = setup

    def fail(_):
        raise IncompleteRead(b"part", 20)

    m.transport = fail
    start(m)
    assert finish(m)["phase"] == "failed"


def test_cancel_aborts_a_blocked_body_and_never_publishes(setup):
    m, entry, _, _ = setup
    entered, aborted = Event(), Event()

    class Body(io.BytesIO):
        def read(self, n=-1):
            entered.set()
            aborted.wait(2)
            return b""

        def abort(self):
            aborted.set()

    m.transport = lambda _: Body()
    start(m)
    assert entered.wait(1)
    job = m.state()["jobs"][entry.id]
    m.cancel(entry.id, job["job_id"])
    assert aborted.wait(0.2)
    assert finish(m)["phase"] == "cancelled"
    assert m.close() and not list(m.root.glob(".partial-*"))


def test_multi_file_bundle_failure_never_publishes_first_file(setup):
    m, entry, content, _ = setup
    other = replace(entry.artifacts[0], filename="features.index", role="index")
    m.entries[entry.id] = replace(entry, artifacts=entry.artifacts + (other,))
    m.transport = lambda url: io.BytesIO(
        content if url.endswith(".gguf") else b"bad second file"
    )
    start(m)
    assert finish(m)["phase"] == "failed"
    assert not list(m.root.rglob("model.gguf"))


def test_catalog_contains_pinned_artifacts_and_no_private_model():
    assert (
        Path(__file__).resolve().parents[2]
        / "src-python/models/model_downloads/catalog.py"
    ).exists()
    from models.model_downloads.catalog import CATALOG, validate_catalog

    validate_catalog(CATALOG)
    assert {m.target for m in CATALOG} == {"japanese", "multilingual", "asr", "rvc"}
    assert "Mia" not in repr(CATALOG)
    for m in CATALOG:
        assert m.licenses and all(
            "/" + m.revision + "/" in url
            or url.startswith(
                ("https://creativecommons.org/", "https://www.apache.org/licenses/")
            )
            for url in m.licenses
        )
        assert m.artifacts and all(a.size > 0 for a in m.artifacts)



def test_haas_recognizer_is_pinned_for_the_asr_profile():
    from models.model_downloads.catalog import CATALOG

    haas = [m for m in CATALOG if m.target == "asr"]
    assert [m.id for m in haas] == ["haas-ja-q8"]
    assert haas[0].license == "Apache-2.0" and haas[0].notice == "haas"
    assert [(a.filename, a.size, a.role) for a in haas[0].artifacts] == [
        ("Haas-616M-ja-v1.0-Q8_0.gguf", 656381472, "model")
    ]

@pytest.mark.parametrize(
    "url",
    [
        "http://huggingface.co/x",
        "https://huggingface.co.evil/x",
        "https://localhost/x",
        "https://user:pass@huggingface.co/x",
        "https://huggingface.co:444/x",
        "http://us.aws.cdn.hf.co/x",
        "https://us.aws.cdn.hf.co.evil/x",
        "https://other.aws.cdn.hf.co/x",
        "https://evil@us.aws.cdn.hf.co/x",
    ],
)
def test_transport_rejects_unapproved_redirects(url):
    assert (
        Path(__file__).resolve().parents[2]
        / "src-python/models/model_downloads/transport.py"
    ).exists()
    from models.model_downloads.transport import validate_url

    with pytest.raises(ValueError):
        validate_url(url)


def test_transport_accepts_exact_observed_hf_delivery_host():
    from urllib.request import Request
    from models.model_downloads.transport import PublicRedirect

    request = Request("https://huggingface.co/owner/model/resolve/fixed/file.gguf")
    target = "https://us.aws.cdn.hf.co/bridge/file?test=nonsecret"
    redirected = PublicRedirect().redirect_request(
        request, None, 302, "Found", {}, target
    )
    assert redirected.full_url == target


def test_memory_variants_have_independent_pinned_artifacts_and_guidance(tmp_path):
    from models.model_downloads.manager import Downloads

    catalog = Downloads(tmp_path / "models").catalog()
    models = {row["id"]: row for row in catalog["models"]}
    assert (
        models["irodori-v41-q8"]["artifacts"][0]["sha256"]
        == "2d161b0bbcd74f906f6b07e03d031075f8ae916db1b8bd4daf16cb37b451086a"
    )
    assert (
        models["qwen3-06b-q5"]["artifacts"][0]["sha256"]
        == "4bb9ba9e822ab614798c416c7f0187994f349be41221966fa911aca24f237930"
    )
    assert models["irodori-v41-q8"]["guidance"]["reference_memory_bytes"] == 1590000000
    assert models["qwen3-06b-q5"]["guidance"]["reference_memory_bytes"] == 990000000
    assert (
        models["irodori-v41-f16"]["guidance"]["reference_memory_bytes"]
        > models["irodori-v41-q8"]["guidance"]["reference_memory_bytes"]
    )
    assert models["rvc-saisho"]["guidance"]["reference_memory_bytes"] is None
