"""External translation can start without an optional local fallback model."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import controller as module
import errors


@pytest.mark.parametrize("engine", ["LMStudio", "Ollama", "OpenAI_API"])
def test_external_translation_without_ctranslate_weights(monkeypatch, engine):
    config = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
        SELECTED_TRANSLATION_ENGINES={"1": engine},
        SELECTABLE_TRANSLATION_ENGINE_STATUS={engine: True, "CTranslate2": False})
    model = MagicMock()
    model.isLoadedCTranslate2Model.return_value = False
    model.changeTranslatorCTranslate2Model.side_effect = RuntimeError("missing weights")
    model.detectVRAMError.return_value = (False, "")
    monkeypatch.setattr(module, "config", config)
    monkeypatch.setattr(module, "model", model)
    monkeypatch.setattr(module, "errorLogging", lambda: None)
    app = module.Controller.__new__(module.Controller)
    assert app.setEnableTranslation() == {"status": 200, "result": True}
    model.changeTranslatorCTranslate2Model.assert_not_called()
    assert app.setDisableTranslation() == {"status": 200, "result": False}


@pytest.mark.parametrize("engine", ["CTranslate2", "LMStudio"])
def test_available_local_fallback_still_loads(monkeypatch, engine):
    config = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
        SELECTED_TRANSLATION_ENGINES={"1": engine},
        SELECTABLE_TRANSLATION_ENGINE_STATUS={engine: True, "CTranslate2": True})
    model = MagicMock()
    model.isLoadedCTranslate2Model.return_value = False
    monkeypatch.setattr(module, "config", config)
    monkeypatch.setattr(module, "model", model)
    app = module.Controller.__new__(module.Controller)
    assert app.setEnableTranslation()["result"] is True
    model.changeTranslatorCTranslate2Model.assert_called_once()
    model.setChangedTranslatorParameters.assert_called_once_with(False)


@pytest.mark.parametrize("has_file, error_code, failure", [
    (False, "TRANSLATION_MODEL_MISSING", False), (True, "TRANSLATION_MODEL_LOAD_FAILED", True)])
def test_a_model_that_cannot_load_is_reported(monkeypatch, has_file, error_code, failure):
    config = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
        SELECTED_TRANSLATION_ENGINES={"1": "CTranslate2"},
        SELECTABLE_TRANSLATION_ENGINE_STATUS={"CTranslate2": False},
        CTRANSLATE2_WEIGHT_TYPE="m2m100_418M-ct2-int8")
    model = MagicMock()
    model.isLoadedCTranslate2Model.return_value = False
    model.changeTranslatorCTranslate2Model.side_effect = RuntimeError("Unable to open file 'model.bin'")
    model.detectVRAMError.return_value = (False, None)
    model.hasTranslatorCTranslate2ModelWeightFile.return_value = has_file
    logged, counted = [], []
    monkeypatch.setattr(module, "config", config)
    monkeypatch.setattr(module, "model", model)
    monkeypatch.setattr(module, "errorLogging", lambda: logged.append(True))
    monkeypatch.setattr(errors, "_error_report_hooks", [counted.append])
    app = module.Controller.__new__(module.Controller)
    response = app.setEnableTranslation()
    assert response["status"] == 400
    assert response["result"]["error_code"] == error_code
    assert response["result"]["data"] is False
    assert config.ENABLE_TRANSLATION is False
    model.hasTranslatorCTranslate2ModelWeightFile.assert_called_once_with("m2m100_418M-ct2-int8")
    # A model that was never downloaded is where every new user starts: the UI opens the
    # download review. It leaves no trace in error.log and is not counted as an error in the
    # usage events. A model that is there and cannot be loaded is both.
    assert bool(logged) is failure
    assert counted == ([error_code] if failure else [])
