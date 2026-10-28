"""External translation can start without an optional local fallback model."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import controller as module


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
