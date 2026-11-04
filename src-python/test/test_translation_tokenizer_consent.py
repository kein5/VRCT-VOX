"""Tokenizers may contact the hub only in the consented download path."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import controller as controller_module
import model as model_module
from models.translation import translation_utils as utils
from models.translation import translation_translator as translator

WEIGHT = "m2m100_418M-ct2-int8"


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("loading", ["inference", "availability", "acquisition"])
def test_tokenizer_flags_and_revision_on_both_cache_paths(monkeypatch, tmp_path, fallback, loading):
    tokenizer = MagicMock()
    tokenizer.from_pretrained.side_effect = [OSError("missing primary cache"), object()] if fallback else [object()]
    fake = SimpleNamespace(AutoTokenizer=tokenizer)
    monkeypatch.setattr(utils, "transformers", fake)
    monkeypatch.setattr(translator, "transformers", fake)
    monkeypatch.setattr(translator, "ctranslate2", MagicMock())
    if loading == "inference":
        instance = translator.Translator()
        instance.changeCTranslate2Model(str(tmp_path), WEIGHT, compute_type="int8")
        assert instance.isLoadedCTranslate2Model()
    elif loading == "availability":
        monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(tmp_path)))
        monkeypatch.setattr(model_module, "checkCTranslate2Weight", lambda *args: True)
        assert model_module.Model.checkTranslatorCTranslate2ModelWeight(None, WEIGHT)
    else:
        monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(tmp_path)))
        model_module.Model.downloadCTranslate2ModelTokenizer(None, WEIGHT)
    assert tokenizer.from_pretrained.call_count == (2 if fallback else 1)
    for call in tokenizer.from_pretrained.call_args_list:
        assert call.args == ("facebook/m2m100_418M",)
        assert call.kwargs["revision"] == utils.TOKENIZER_REVISIONS["facebook/m2m100_418M"]
        assert call.kwargs["local_files_only"] is (loading != "acquisition")


def test_missing_tokenizer_disables_availability_and_maps_enable_to_model_missing(monkeypatch, tmp_path):
    tokenizer = MagicMock()
    tokenizer.from_pretrained.side_effect = OSError("no local tokenizer")
    fake = SimpleNamespace(AutoTokenizer=tokenizer)
    monkeypatch.setattr(utils, "transformers", fake)
    monkeypatch.setattr(translator, "transformers", fake)
    monkeypatch.setattr(translator, "ctranslate2", MagicMock())
    monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(tmp_path)))
    monkeypatch.setattr(model_module, "checkCTranslate2Weight", lambda *args: True)
    assert model_module.Model.checkTranslatorCTranslate2ModelWeight(None, WEIGHT) is False
    instance = translator.Translator()
    backend = MagicMock()
    backend.isLoadedCTranslate2Model.return_value = False
    backend.hasTranslatorCTranslate2ModelWeightFile.return_value = True
    backend.detectVRAMError.return_value = (False, "")
    backend.changeTranslatorCTranslate2Model.side_effect = lambda: instance.changeCTranslate2Model(str(tmp_path), WEIGHT, compute_type="int8")
    monkeypatch.setattr(controller_module, "model", backend)
    config = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
        SELECTED_TRANSLATION_ENGINES={"1": "CTranslate2"}, CTRANSLATE2_WEIGHT_TYPE=WEIGHT)
    monkeypatch.setattr(controller_module, "config", config)
    app = controller_module.Controller.__new__(controller_module.Controller)
    response = app.setEnableTranslation()
    assert response["result"]["error_code"] == "TRANSLATION_MODEL_MISSING"
    assert response["result"]["data"] is False
    assert not config.ENABLE_TRANSLATION
    assert not instance.isLoadedCTranslate2Model()
    assert all(call.kwargs["local_files_only"] is True for call in tokenizer.from_pretrained.call_args_list)
