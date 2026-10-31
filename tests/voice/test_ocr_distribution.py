"""Builds ship the RapidOCR code and config, never OCR weights or the upstream detector."""

from pathlib import Path
import sys
import tomllib
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tools.distribution_policy import OCR_RUNTIME_DATA, filter_toc, missing_ocr_runtime, violation
from tools.linux_package import RUNTIME, check_tree

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", [
    "rapidocr/__init__.py", "rapidocr/main.py", "rapidocr/config.yaml", "rapidocr/default_models.yaml",
    "_internal/rapidocr/inference_engine/onnxruntime/main.py",
])
def test_rapidocr_code_and_config_are_allowed(name):
    assert violation(name) is None


@pytest.mark.parametrize("name", [
    "_internal/rapidocr/models/PP-OCRv6_det_small.onnx",
    "_internal/rapidocr/models/PP-OCRv6_rec_small.onnx",
    "_internal/rapidocr/models/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "_internal/ocr_onnx/chatbox_yolox_tiny.onnx",
    # The upstream detector stays out under any container or format.
    "_internal/chatbox_yolox_tiny.ort", "data/chatbox_yolox_tiny.onnx.zst", "x/CHATBOX_YOLOX_TINY.bin",
    # Downloaded PP-OCR files never travel with a build either.
    "downloaded_models/ppocrv6-small/rev/det.onnx",
    # Nor does VRCT-VOX's own detector: it is a consented download as well.
    "_internal/vrct_vox_chatbox_yolox_tiny.onnx",
    "downloaded_models/vrct-vox-chatbox-detector/rev/vrct_vox_chatbox_yolox_tiny.onnx",
])
def test_ocr_weights_and_detector_are_rejected(name):
    assert violation(name) == "Restricted OCR model"


def test_toc_filter_keeps_runtime_data_and_drops_bundled_weights():
    entries = [
        ("rapidocr/config.yaml", "site-packages/rapidocr/config.yaml", "DATA"),
        ("rapidocr/default_models.yaml", "site-packages/rapidocr/default_models.yaml", "DATA"),
        ("rapidocr/models/PP-OCRv6_rec_small.onnx", "site-packages/rapidocr/models/PP-OCRv6_rec_small.onnx", "DATA"),
        ("ocr_onnx/chatbox_yolox_tiny.onnx", "src-python/models/ocr/onnx/chatbox_yolox_tiny.onnx", "DATA"),
    ]
    kept = [entry[0] for entry in filter_toc(entries)]
    assert kept == ["rapidocr/config.yaml", "rapidocr/default_models.yaml"]
    assert missing_ocr_runtime(kept) == []
    assert missing_ocr_runtime(["_internal/rapidocr/config.yaml"]) == ["rapidocr/default_models.yaml"]


def test_linux_runtime_inventory_requires_rapidocr_config():
    for name in OCR_RUNTIME_DATA:
        assert "_internal/" + name in RUNTIME


def test_linux_tree_with_rapidocr_code_but_no_weights_passes(tmp_path):
    package = tmp_path / "_internal/rapidocr"
    (package / "models").mkdir(parents=True)
    for name in ("__init__.py", "config.yaml", "default_models.yaml", "models/.gitkeep"):
        (package / name).write_text("x")
    check_tree(tmp_path)
    (package / "models/PP-OCRv6_rec_small.onnx").write_bytes(b"weights")
    with pytest.raises(ValueError, match="Restricted OCR"):
        check_tree(tmp_path)


def test_rapidocr_is_a_dependency_on_every_platform():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pins = [d for d in project["project"]["dependencies"] if d.replace(" ", "").startswith("rapidocr==")]
    assert pins == ["rapidocr==3.9.2"]
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert '{ name = "rapidocr", marker' not in lock
    assert '{ name = "rapidocr", specifier = "==3.9.2" }' in lock


def _exec_spec(name, extra_scope=None):
    analysis = SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
    analyze = MagicMock(return_value=analysis)
    scope = {"SPECPATH": str(ROOT / "spec"), "Analysis": analyze, "PYZ": MagicMock(), "EXE": MagicMock(),
             "COLLECT": MagicMock(), **(extra_scope or {})}
    exec(compile((ROOT / "spec" / name).read_text(encoding="utf-8"), name, "exec"), scope)
    return analyze.call_args.kwargs


@pytest.mark.parametrize("spec_name", ["backend.spec", "backend_cuda.spec"])
def test_windows_specs_collect_rapidocr_config_only(spec_name):
    kwargs = _exec_spec(spec_name)
    assert "rapidocr" in kwargs["hiddenimports"]
    assert "rapidocr.inference_engine.onnxruntime" in kwargs["hiddenimports"]
    sources = [source.replace("\\", "/") for source, _ in kwargs["datas"]]
    for name in OCR_RUNTIME_DATA:
        assert any(source.endswith("site-packages/" + name) for source in sources)
    assert not any(source.rstrip("/").endswith("site-packages/rapidocr") for source in sources)
    assert "rapidocr" not in kwargs["excludes"]


def test_linux_spec_collects_rapidocr_and_no_longer_excludes_it(monkeypatch, tmp_path):
    calls = []

    def collect_data_files(package, **options):
        calls.append((package, options))
        return []

    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = collect_data_files
    hooks.collect_dynamic_libs = lambda package: []
    hooks.copy_metadata = lambda package: []
    for name, module in (("PyInstaller", ModuleType("PyInstaller")), ("PyInstaller.utils", ModuleType("PyInstaller.utils")),
                         ("PyInstaller.utils.hooks", hooks)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("VRCT_LINUX_RESOURCES", str(tmp_path))
    kwargs = _exec_spec("backend_linux.spec")
    assert "rapidocr" not in kwargs["excludes"]
    assert {"rapidocr", "rapidocr.inference_engine.onnxruntime"} <= set(kwargs["hiddenimports"])
    assert ("rapidocr", {"includes": ["*.yaml"]}) in calls
