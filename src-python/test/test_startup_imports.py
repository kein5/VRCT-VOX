"""The backend must start without importing libraries a default setup never uses."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from models import sdk_clients
from models.ocr import ocr_engine_rapidocr as ocr_engine
from models.transcription import transcription_whisper as whisper
from models.translation import translation_utils as utils

DEFERRED = ("openai", "langchain_openai", "langchain_ollama", "langchain_google_genai",
            "google.genai", "pydantic", "transformers", "faster_whisper", "rapidocr")


def test_importing_the_controller_leaves_heavy_libraries_unloaded(tmp_path):
    code = f"import json, sys, controller; print(json.dumps([n for n in {DEFERRED!r} if n in sys.modules]))"
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            env=dict(os.environ, VRCT_CONFIG_DIR=str(tmp_path)),
                            capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == []


def module_with(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def test_sdk_factories_pass_arguments_to_the_real_class(monkeypatch):
    client = Mock(return_value="built")
    monkeypatch.setitem(sys.modules, "openai", module_with("openai", OpenAI=client))
    assert sdk_clients.OpenAI("key", base_url="url") == "built"
    client.assert_called_once_with("key", base_url="url")


def test_genai_client_uses_the_loaded_module(monkeypatch):
    client = Mock(return_value="built")
    google = module_with("google", genai=SimpleNamespace(Client=client))
    monkeypatch.setitem(sys.modules, "google", google)
    assert sdk_clients.genai.Client(api_key="key") == "built"
    client.assert_called_once_with(api_key="key")


def test_transformers_loads_once_and_a_missing_package_is_remembered(monkeypatch):
    monkeypatch.setattr(utils, "transformers", utils.UNLOADED)
    monkeypatch.setitem(sys.modules, "transformers", None)
    assert utils.loadTransformers() is None
    assert utils.transformers is None
    # Already answered: installing it later in this process changes nothing.
    monkeypatch.setitem(sys.modules, "transformers", module_with("transformers"))
    assert utils.loadTransformers() is None


def test_whisper_class_loads_on_first_model(monkeypatch):
    model_class = Mock()
    monkeypatch.setattr(whisper, "WhisperModel", whisper._UNLOADED)
    monkeypatch.setitem(sys.modules, "faster_whisper", module_with("faster_whisper", WhisperModel=model_class))
    assert whisper._loadWhisperModelClass() is model_class
    assert whisper.WhisperModel is model_class


def test_missing_whisper_package_keeps_the_existing_error(monkeypatch):
    monkeypatch.setattr(whisper, "WhisperModel", whisper._UNLOADED)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(RuntimeError, match="faster_whisper is not installed"):
        whisper.getWhisperModel("root", "tiny")


def test_rapidocr_is_blocked_from_downloading_before_it_is_used(monkeypatch):
    blocked = Mock()
    engine = Mock()
    monkeypatch.setattr(ocr_engine, "RapidOCR", ocr_engine._UNLOADED)
    monkeypatch.setattr(ocr_engine, "_blockImplicitDownloads", blocked)
    monkeypatch.setitem(sys.modules, "rapidocr", module_with(
        "rapidocr", RapidOCR=engine, EngineType=Mock(), LangRec=Mock(), ModelType=Mock(), OCRVersion=Mock()))
    assert ocr_engine.isAvailable() is True
    assert ocr_engine.RapidOCR is engine
    blocked.assert_called_once_with()


def test_failed_rapidocr_import_reports_unavailable(monkeypatch):
    monkeypatch.setattr(ocr_engine, "RapidOCR", ocr_engine._UNLOADED)
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    assert ocr_engine.isAvailable() is False
    assert ocr_engine.getReader(object(), object()) is None
