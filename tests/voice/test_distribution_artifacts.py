import io
import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from tools import check_voice_distribution as guard


@pytest.mark.parametrize("name", [
    "ocr_onnx/renamed.onnx", "rapidocr/models/rec.onnx",
    "CH_PP-OCRv4_det_infer.onnx", "models/ocr/weights/model.pth",
])
def test_all_ocr_weights_are_rejected_in_tree_and_zip(tmp_path, name):
    model = tmp_path / name
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"synthetic model")
    with pytest.raises(ValueError, match="OCR"):
        guard.check([tmp_path])
    output = tmp_path / "package.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.write(model, name.upper().replace("/", "\\"))
    model.unlink()
    with pytest.raises(ValueError, match="OCR"):
        guard.check([output])



@pytest.mark.parametrize("name,reason", [
    ("_internal/av.libs/libx264-d6533a8d.so.165", "GPL codec"),
    ("_internal/av.libs/libavcodec-5e6b81c2.so.62.28.102", "PyAV"),
    ("_internal/av/_core.abi3.so", "PyAV"),
    ("_internal/av.libs/x265-215.dll", "GPL codec"),
    ("_internal/av/_core.cp311-win_amd64.pyd", "PyAV"),
])
def test_pyav_and_gpl_encoders_are_rejected(tmp_path, name, reason):
    with zipfile.ZipFile(tmp_path / "package.zip", "w") as archive:
        archive.writestr(name, b"synthetic library")
    with pytest.raises(ValueError, match=reason):
        guard.check([tmp_path])


def test_lgpl_opencv_ffmpeg_and_the_pyav_stand_in_remain_allowed(tmp_path):
    with zipfile.ZipFile(tmp_path / "package.zip", "w") as archive:
        archive.writestr("_internal/opencv_python_headless.libs/libavcodec-9aae324f.so.59.37.100", b"lgpl")
        archive.writestr("_internal/cv2/opencv_videoio_ffmpeg4100_64.dll", b"lgpl")
        archive.writestr("_internal/soxr/soxr_ext.cpython-311-x86_64-linux-gnu.so", b"lgpl")
    guard.check([tmp_path])


def test_pyav_stand_in_imports_without_its_native_code():
    stub = Path(__file__).resolve().parents[2] / "packaging/pyinstaller-stubs/av/__init__.py"
    namespace = {}
    exec(compile(stub.read_text(encoding="utf-8"), str(stub), "exec"), namespace)
    with pytest.raises(AttributeError, match="not included"):
        namespace["__getattr__"]("open")

def test_guard_inspects_nested_zip_in_tree_and_zip(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("ocr_onnx/chatbox_yolox_tiny.onnx", b"synthetic")
    outer = tmp_path / "package.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("nested.zip", payload.getvalue())
    for path in [outer, tmp_path]:
        with pytest.raises(ValueError, match="OCR"):
            guard.check([path])


def test_guard_rejects_unreadable_zip(tmp_path):
    broken = tmp_path / "package.zip"
    broken.write_bytes(b"truncated zip")
    with pytest.raises(ValueError, match="inspect"):
        guard.check([broken])


def test_non_ocr_vad_and_notices_remain_allowed(tmp_path):
    with zipfile.ZipFile(tmp_path / "package.zip", "w") as archive:
        archive.writestr("faster_whisper/assets/silero_vad_v6.onnx", b"fake VAD")
        archive.writestr("ocr_onnx/LICENSE.txt", "attribution")
    guard.check([tmp_path])


@pytest.mark.parametrize("entry", ["ocr_onnx/chatbox_yolox_tiny.onnx", "rapidocr/models/rec.onnx", "voice/Mia2026.pth"])
def test_nsis_payload_listing_rejects_prohibited_assets(tmp_path, monkeypatch, entry):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ fake installer")
    def run(args, **kwargs):
        assert args[:3] == ["7z", "l", "-slt"]
        assert args[-1] == str(installer)
        return SimpleNamespace(returncode=0, stdout=f"Path = {installer}\nType = Nsis\n\n----------\nPath = {entry}\nSize = 20\n", stderr="")
    monkeypatch.setattr("subprocess.run", run)
    with pytest.raises(ValueError, match="OCR|Private voice"):
        guard.check_nsis([installer])


@pytest.mark.parametrize("listing", ["", "Type = PE\n\n----------\nPath = .text\n", "Type = Nsis\n\n----------\nPath = unchecked.zip\n"])
def test_nsis_unknown_or_nested_payload_never_passes(tmp_path, monkeypatch, listing):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"fake")
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=listing, stderr=""))
    with pytest.raises(ValueError):
        guard.check_nsis([installer])


def test_nsis_clean_listing_and_inspector_failure(tmp_path, monkeypatch):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"fake")
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="Type = Nsis\n\n----------\nPath = LICENSE.txt\nSize = 100\n", stderr=""))
    guard.check_nsis([installer])
    def fail(*a, **kw):
        raise FileNotFoundError("no 7z")
    monkeypatch.setattr("subprocess.run", fail)
    with pytest.raises(ValueError, match="inspect"):
        guard.check_nsis([installer])


@pytest.mark.skipif(shutil.which("7z") is None, reason="7-Zip not installed")
def test_real_7zip_listing_does_not_mistake_zip_for_nsis(tmp_path, monkeypatch):
    candidate = tmp_path / "setup.exe"
    with zipfile.ZipFile(candidate, "w") as archive:
        archive.writestr("LICENSE.txt", "synthetic")
    original = subprocess.run
    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result.returncode == 0, result.stderr
        assert "Type = zip" in result.stdout
        return result
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="Cannot inspect NSIS"):
        guard.check_nsis([candidate])


def _zip_builder():
    path = Path(__file__).resolve().parents[2] / "utils/zip.py"
    spec = importlib.util.spec_from_file_location("fork_zip_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.zip_files_and_directory


def test_package_builder_refuses_missing_inputs_before_replacing_output(tmp_path):
    output = tmp_path / "fork.zip"
    output.write_bytes(b"previous candidate")
    with pytest.raises(ValueError, match="exist"):
        _zip_builder()(output, [tmp_path / "missing.exe"], [])
    assert output.read_bytes() == b"previous candidate"


def test_package_builder_propagates_io_failure(tmp_path, monkeypatch):
    source = tmp_path / "app.exe"
    source.write_bytes(b"fake executable")
    def fail(*args, **kwargs):
        raise OSError("synthetic disk full")
    monkeypatch.setattr(zipfile.ZipFile, "write", fail)
    with pytest.raises(OSError, match="disk full"):
        _zip_builder()(tmp_path / "fork.zip", [source], [])


def test_package_builder_creates_auditable_zip(tmp_path):
    source = tmp_path / "app.exe"
    source.write_bytes(b"fake executable")
    resources = tmp_path / "_internal"
    resources.mkdir()
    (resources / "LICENSE.txt").write_text("retain original attribution")
    output = tmp_path / "fork.zip"
    _zip_builder()(output, [source], [resources])
    guard.check([output])
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"app.exe", "_internal/LICENSE.txt"}
        assert archive.testzip() is None
