"""OCR (chat reading) models in the consented download catalog. No network."""

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import time

import pytest

from models.model_downloads.catalog import CATALOG, OCR_CATALOG, Artifact, Model, artifact_url, validate_catalog
from models.model_downloads.manager import Downloads


# Measured on 2026-11-01 by downloading each pinned file from Hugging Face and
# hashing it locally; they also match the LFS metadata the Hub API reports.
VERIFIED = {
    ("ppocrv6-small", "det.onnx"): (9880512, "d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e"),
    ("ppocrv6-small", "rec.onnx"): (21159378, "5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634"),
    ("ppocrv6-small", "rec.yml"): (150579, "ab078671bb49f06228eadccd34f1bb501e157f7a047095ffb943ba81512c77d1"),
    ("ppocrv5-korean", "rec.onnx"): (13418787, "92f0b7785e64fc9090106a241cf4c1eb97472824558272751b88a2a4476d3a08"),
}


def test_ocr_entries_are_pinned_official_apache_models():
    validate_catalog(CATALOG)
    ocr = [m for m in CATALOG if m.target == "ocr"]
    assert [m.id for m in ocr] == [m.id for m in OCR_CATALOG]
    assert ocr[0].id == "ppocrv6-small"
    for model in ocr:
        assert model.license == "Apache-2.0" and model.notice == "ppocr"
        for artifact in model.artifacts:
            repo, revision, path = artifact.remote
            assert repo.startswith("PaddlePaddle/") and repo.endswith("_onnx")
            assert path in ("inference.onnx", "inference.yml") and len(revision) == 40
            assert artifact_url(model, artifact) == f"https://huggingface.co/{repo}/resolve/{revision}/{path}"
    files = {(m.id, a.filename): (a.size, a.sha256) for m in ocr for a in m.artifacts}
    for key, expected in VERIFIED.items():
        assert files[key] == expected
    # The base download carries the detector every script recogniser uses.
    assert {a.role for a in ocr[0].artifacts} == {"det", "rec", "dict"}
    assert all({a.role for a in m.artifacts} == {"rec", "dict"} for m in ocr[1:])


def test_upstream_chatbox_detector_is_never_downloadable():
    for model in CATALOG:
        for artifact in model.artifacts:
            names = (artifact.filename, *artifact.remote)
            assert not any("chatbox" in name.lower() or "yolo" in name.lower() for name in names)


@pytest.mark.parametrize("change", [
    {"remote": ("PaddlePaddle/x", "short", "inference.onnx")},
    {"remote": ("PaddlePaddle/x", "b" * 40, "../inference.onnx")},
    {"remote": ("not a repo", "b" * 40, "inference.onnx")},
    {"remote": ("PaddlePaddle/x", "b" * 40)},
    {"filename": "det.gguf"},
    {"role": "model"},
])
def test_invalid_ocr_artifacts_are_rejected(change):
    base = OCR_CATALOG[0]
    broken = replace(base, artifacts=(replace(base.artifacts[0], **change), *base.artifacts[1:]))
    with pytest.raises(ValueError, match="catalog_invalid"):
        validate_catalog((broken,))


def test_ocr_roles_and_suffixes_stay_out_of_other_targets():
    entry = Model("tts", "japanese", "T", "A", "a/b", "a" * 40, "MIT", ("x",), "irodori",
                  (Artifact("det.onnx", 1, "0" * 64, "det"),))
    with pytest.raises(ValueError, match="catalog_invalid"):
        validate_catalog((entry,))


def test_files_from_two_repositories_land_in_one_verified_directory(tmp_path):
    payloads = {"det.onnx": b"det-bytes", "rec.onnx": b"rec-bytes" * 3, "rec.yml": b"PostProcess: {}\n"}
    artifacts = tuple(
        Artifact(name, len(body), hashlib.sha256(body).hexdigest(), role,
                 (repo, rev, remote_name))
        for (name, body), role, (repo, rev, remote_name) in zip(
            payloads.items(), ("det", "rec", "dict"),
            (("Org/det_onnx", "c" * 40, "inference.onnx"), ("Org/rec_onnx", "d" * 40, "inference.onnx"),
             ("Org/rec_onnx", "d" * 40, "inference.yml"))))
    entry = Model("ocr-test", "ocr", "OCR", "Org", "Org/rec_onnx", "d" * 40, "Apache-2.0",
                  ("https://www.apache.org/licenses/LICENSE-2.0",), "ppocr", artifacts)
    by_url = {artifact_url(entry, a): payloads[a.filename] for a in artifacts}
    opened = []

    def transport(url):
        opened.append(url)
        return io.BytesIO(by_url[url])

    manager = Downloads(tmp_path / "models", catalog=(entry,), transport=transport, reserve_bytes=0)
    try:
        manager.start({"id": "ocr-test", "consent": True, "catalog_version": manager.catalog_version})
        end = time.monotonic() + 3
        while manager.state()["jobs"]["ocr-test"]["phase"] not in ("ready", "failed") and time.monotonic() < end:
            time.sleep(0.005)
        job = manager.state()["jobs"]["ocr-test"]
        assert job["phase"] == "ready", job
        assert opened == [
            "https://huggingface.co/Org/det_onnx/resolve/" + "c" * 40 + "/inference.onnx",
            "https://huggingface.co/Org/rec_onnx/resolve/" + "d" * 40 + "/inference.onnx",
            "https://huggingface.co/Org/rec_onnx/resolve/" + "d" * 40 + "/inference.yml",
        ]
        assert {role: Path(path).name for role, path in job["paths"].items()} == {
            "det": "det.onnx", "rec": "rec.onnx", "dict": "rec.yml"}
        row = manager.catalog()["models"][0]
        assert row["sources"] == ["https://huggingface.co/Org/det_onnx/tree/" + "c" * 40,
                                  "https://huggingface.co/Org/rec_onnx/tree/" + "d" * 40]
    finally:
        manager.close()
