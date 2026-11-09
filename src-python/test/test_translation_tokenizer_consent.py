"""Tokenizers load a verified projection of the consented CT2 bundle, always offline."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as controller_module
import model as model_module
from models.translation import translation_utils as utils
from models.translation import translation_translator as translator


@pytest.fixture(params=["m2m100_418M-ct2-int8", "nllb-200-distilled-600M-ct2-int8"])
def bundle(tmp_path, monkeypatch, request):
    weight = request.param
    repo = utils.ctranslate2_weights[weight]["hf_repo"]
    bodies = {"model.bin": b"weights", "tokenizer_config.json": b"config"}
    bodies.update({"vocab.json": b"vocab", "sentencepiece.bpe.model": b"sentencepiece"}
                  if weight.startswith("m2m100") else {"tokenizer.json": b"nllb-tokenizer"})
    monkeypatch.setitem(utils.MODEL_PINS, repo, {"revision": "a" * 40, "files": {
        name: (len(body), hashlib.sha256(body).hexdigest()) for name, body in bodies.items()
    }})
    path = tmp_path / "weights/ctranslate2" / weight
    path.mkdir(parents=True)
    for name, body in bodies.items():
        (path / name).write_bytes(body)
    (path / "added_tokens.json").write_bytes(b"untrusted extra file")
    return tmp_path, weight, path, bodies


@pytest.mark.parametrize("loading", ["inference", "acquisition"])
def test_only_verified_tokenizer_files_reach_local_loader(bundle, monkeypatch, loading):
    root, weight, path, bodies = bundle
    calls = []

    def load(directory, **kwargs):
        calls.append(kwargs)
        projection = Path(directory)
        assert projection != path
        filename = "vocab.json" if weight.startswith("m2m100") else "tokenizer.json"
        assert (projection / filename).read_bytes() == bodies[filename]
        assert not (projection / "added_tokens.json").exists()
        assert not (projection / "model.bin").exists()
        assert kwargs == {"local_files_only": True}
        return object()

    fake = SimpleNamespace(M2M100Tokenizer=SimpleNamespace(from_pretrained=load),
                           NllbTokenizerFast=SimpleNamespace(from_pretrained=load))
    monkeypatch.setattr(utils, "transformers", fake)
    monkeypatch.setattr(translator, "transformers", fake)
    monkeypatch.setattr(translator, "ctranslate2", Mock())
    monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(root)))
    if loading == "inference":
        instance = translator.Translator()
        instance.changeCTranslate2Model(str(root), weight, compute_type="int8")
        assert instance.isLoadedCTranslate2Model()
    else:
        model_module.Model.downloadCTranslate2ModelTokenizer(None, weight)
    assert len(calls) == 1


def test_availability_needs_the_hashes_but_not_transformers(bundle, monkeypatch):
    root, weight, path, bodies = bundle
    load = Mock()
    monkeypatch.setattr(utils, "loadTransformers", load)
    monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(root)))
    assert model_module.Model.checkTranslatorCTranslate2ModelWeight(None, weight) is True
    filename = "vocab.json" if weight.startswith("m2m100") else "tokenizer.json"
    (path / filename).write_bytes(b"x" * len(bodies[filename]))
    assert model_module.Model.checkTranslatorCTranslate2ModelWeight(None, weight) is False
    load.assert_not_called()


def test_missing_or_mismatched_tokenizer_rejects_before_parser(bundle, monkeypatch):
    root, weight, path, bodies = bundle
    fake = Mock()
    monkeypatch.setattr(utils, "transformers", fake)
    filename = "vocab.json" if weight.startswith("m2m100") else "tokenizer.json"
    (path / filename).write_bytes(b"x" * len(bodies[filename]))
    with pytest.raises(utils.MissingCTranslate2Tokenizer):
        utils.downloadCTranslate2Tokenizer(root, weight, local_files_only=False)
    fake.M2M100Tokenizer.from_pretrained.assert_not_called()
    fake.NllbTokenizerFast.from_pretrained.assert_not_called()
    assert (path / filename).exists()


def test_missing_tokenizer_maps_enable_to_model_missing(bundle, monkeypatch):
    root, weight, _, _ = bundle
    monkeypatch.setattr(utils, "transformers", SimpleNamespace(
        M2M100Tokenizer=SimpleNamespace(from_pretrained=Mock(side_effect=OSError("missing"))),
        NllbTokenizerFast=SimpleNamespace(from_pretrained=Mock(side_effect=OSError("missing")))))
    monkeypatch.setattr(translator, "transformers", Mock())
    monkeypatch.setattr(translator, "ctranslate2", Mock())
    monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(root)))
    instance = translator.Translator()
    backend = Mock()
    backend.isLoadedCTranslate2Model.return_value = False
    backend.hasTranslatorCTranslate2ModelWeightFile.return_value = True
    backend.detectVRAMError.return_value = (False, "")
    backend.changeTranslatorCTranslate2Model.side_effect = lambda: instance.changeCTranslate2Model(str(root), weight, compute_type="int8")
    monkeypatch.setattr(controller_module, "model", backend)
    config = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
        SELECTED_TRANSLATION_ENGINES={"1": "CTranslate2"}, CTRANSLATE2_WEIGHT_TYPE=weight)
    monkeypatch.setattr(controller_module, "config", config)
    app = controller_module.Controller.__new__(controller_module.Controller)
    response = app.setEnableTranslation()
    assert response["result"]["error_code"] == "TRANSLATION_MODEL_MISSING"
    assert response["result"]["data"] is False
    assert not config.ENABLE_TRANSLATION and not instance.isLoadedCTranslate2Model()
