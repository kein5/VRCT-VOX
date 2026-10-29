import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import zipfile

import pytest

from tools.check_voice_distribution import check


def test_old_config_migrates_silently_and_settings_roundtrip(tmp_path):
    from config import Config, ConfigValidationError
    cfg = object.__new__(Config)
    cfg.init_config()
    cfg._PATH_CONFIG = str(tmp_path / "config.json")
    Path(cfg._PATH_CONFIG).write_text('{"UI_LANGUAGE":"en"}', encoding="utf-8")
    try:
        cfg.load_config()
        assert cfg.VOICE_SETTINGS["mode"] == "off"
        assert cfg.VOICE_SETTINGS["japanese_server"] == "external"
        assert cfg.REALTIME_ASR_SETTINGS["server"] == "external"
        assert cfg.SPEECH_SERVER_SETTINGS["profiles"]["asr"]["model"] == ""
        cfg.SPEECH_SERVER_SETTINGS = {"profiles": {"asr": {"model": "/missing/model.gguf"}}}
        cfg.VOICE_SETTINGS = {"mode": "original", "output_device": "explicit-cable"}
        cfg.saveConfigToFile()
        persisted = json.loads(Path(cfg._PATH_CONFIG).read_text(encoding="utf-8"))
        assert persisted["VOICE_SETTINGS"]["output_device"] == "explicit-cable"
        assert persisted["VOICE_SETTINGS"]["japanese_voice"] == "none"
        assert persisted["SPEECH_SERVER_SETTINGS"]["profiles"]["asr"]["model"] == "/missing/model.gguf"
        with pytest.raises(ConfigValidationError):
            cfg.SPEECH_SERVER_SETTINGS = {"active": True}
        with pytest.raises(ConfigValidationError):
            cfg.VOICE_SETTINGS = {"mode": "original", "japanese_url": "http://outside"}
        assert cfg.VOICE_SETTINGS["output_device"] == "explicit-cable"
        cfg.init_config()
        cfg._PATH_CONFIG = str(tmp_path / "config.json")
        cfg.load_config()
        assert cfg.VOICE_SETTINGS["mode"] == "original"
        assert cfg.SPEECH_SERVER_SETTINGS == persisted["SPEECH_SERVER_SETTINGS"]
    finally:
        timer = getattr(cfg, "_timer", None)
        if timer:
            timer.cancel()


@pytest.mark.parametrize("spec_name", ["backend.spec", "backend_cuda.spec"])
def test_pyinstaller_filters_restricted_weight_from_expanded_toc(spec_name):
    root = Path(__file__).resolve().parents[2]
    analysis = SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[
        ("ocr_onnx/chatbox_yolox_tiny.onnx", "some/source", "DATA"),
        ("other\\CHATBOX_YOLOX_TINY.ONNX", "source", "DATA"),
        ("ocr_onnx/LICENSE.txt", "license", "DATA"),
        ("ocr_onnx/ppocr.onnx", "permitted-model", "DATA"),
        ("voice/Mia2026.pth", "private-checkpoint", "DATA"),
        ("voice/Mia2026.index", "private-index", "DATA"),
        ("voice/Mia2026.zip", "private-package", "DATA"),
        ("voice/Mia2026.png", "private-image", "DATA"),
    ])
    collect = MagicMock()
    scope = {"Analysis": lambda *args, **kwargs: analysis, "PYZ": MagicMock(), "EXE": MagicMock(), "COLLECT": collect}
    exec(compile((root / "spec" / spec_name).read_text(encoding="utf-8"), spec_name, "exec"), scope)
    assert [entry[0] for entry in analysis.datas] == ["ocr_onnx/LICENSE.txt", "ocr_onnx/ppocr.onnx"]
    assert collect.call_args.args[2] == analysis.datas


def test_distribution_guard_catches_stale_trees_and_zips(tmp_path):
    (tmp_path / "LICENSE.txt").write_text("keep attribution", encoding="utf-8")
    check([tmp_path])
    model = tmp_path / "chatbox_yolox_tiny.onnx"
    model.write_bytes(b"FAKE MODEL")
    with pytest.raises(ValueError, match="Restricted OCR"):
        check([tmp_path])
    archive_path = tmp_path / "fork.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(model, "_internal/ocr_onnx/chatbox_yolox_tiny.onnx")
    model.unlink()
    with pytest.raises(ValueError, match="Restricted OCR"):
        check([archive_path])


@pytest.mark.parametrize('name', ['Mia2026.pth', 'Mia2026.index', 'Mia2026.zip', 'Mia2026.png'])
def test_user_supplied_rvc_assets_cannot_enter_distribution(tmp_path, name):
    model = tmp_path / name
    model.write_bytes(b'FAKE PRIVATE ASSET')
    with pytest.raises(ValueError, match='Private voice'):
        check([tmp_path])
    with pytest.raises(ValueError, match='Private voice'):
        check([model])
    archive_path = tmp_path / 'fork.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.write(model, 'assets/' + name.upper())
    model.unlink()
    with pytest.raises(ValueError, match='Private voice'):
        check([archive_path])
