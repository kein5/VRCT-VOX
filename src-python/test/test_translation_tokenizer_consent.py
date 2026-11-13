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


def enable_translation(root, weight, monkeypatch):
    """Presses Translation in a Controller whose model loads the real Translator from root."""
    monkeypatch.setattr(translator, "transformers", Mock())
    monkeypatch.setattr(translator, "ctranslate2", Mock())
    monkeypatch.setattr(model_module, "config", SimpleNamespace(PATH_DATA=str(root)))
    instance = translator.Translator()
    backend = Mock()
    backend.isLoadedCTranslate2Model.return_value = False
    backend.hasTranslatorCTranslate2ModelWeightFile.side_effect = lambda name: utils.hasCTranslate2WeightFile(str(root), name)
    backend.detectVRAMError.return_value = (False, "")
    backend.changeTranslatorCTranslate2Model.side_effect = lambda: instance.changeCTranslate2Model(str(root), weight, compute_type="int8")
    monkeypatch.setattr(controller_module, "model", backend)
    config = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
        SELECTED_TRANSLATION_ENGINES={"1": "CTranslate2"}, CTRANSLATE2_WEIGHT_TYPE=weight)
    monkeypatch.setattr(controller_module, "config", config)
    app = controller_module.Controller.__new__(controller_module.Controller)
    return app.setEnableTranslation(), config, instance


def test_a_tokenizer_that_cannot_be_built_from_verified_files_is_a_load_failure(bundle, monkeypatch):
    # The files are the pinned ones. Sending the user to Downloads would fetch nothing new,
    # fail the same way and open the review again, for ever.
    root, weight, _, _ = bundle
    monkeypatch.setattr(utils, "transformers", SimpleNamespace(
        M2M100Tokenizer=SimpleNamespace(from_pretrained=Mock(side_effect=OSError("library failure"))),
        NllbTokenizerFast=SimpleNamespace(from_pretrained=Mock(side_effect=OSError("library failure")))))
    with pytest.raises(utils.CTranslate2TokenizerLoadError):
        utils.downloadCTranslate2Tokenizer(root, weight)
    response, config, instance = enable_translation(root, weight, monkeypatch)
    assert response["result"]["error_code"] == "TRANSLATION_MODEL_LOAD_FAILED"
    assert response["result"]["data"] is False
    assert not config.ENABLE_TRANSLATION and not instance.isLoadedCTranslate2Model()


def test_a_package_whose_transformers_cannot_import_the_tokenizer_is_a_load_failure(bundle, monkeypatch):
    # Every Windows package up to 0.1.0-beta.7: `import transformers` worked, and the first
    # use of a tokenizer class raised FileNotFoundError from inside the library, because it
    # lists the folder next to a __file__ that is not on the disk. A FileNotFoundError is
    # not, by itself, a missing model.
    root, weight, _, _ = bundle

    class Broken:
        def __getattr__(self, name):
            raise FileNotFoundError(2, "The system cannot find the path specified", r"_internal\transformers\models\__init__.pyc")
    monkeypatch.setattr(utils, "transformers", Broken())
    with pytest.raises(utils.CTranslate2TokenizerLoadError) as raised:
        utils.downloadCTranslate2Tokenizer(root, weight)
    assert not isinstance(raised.value, utils.MissingCTranslate2Tokenizer)
    response, config, _ = enable_translation(root, weight, monkeypatch)
    assert response["result"]["error_code"] == "TRANSLATION_MODEL_LOAD_FAILED"
    assert not config.ENABLE_TRANSLATION
    # Transformers that cannot be imported at all is the same kind of failure.
    monkeypatch.setattr(utils, "transformers", None)
    with pytest.raises(utils.CTranslate2TokenizerLoadError):
        utils.downloadCTranslate2Tokenizer(root, weight)


def test_tokenizer_files_that_are_gone_are_still_a_missing_model(bundle, monkeypatch):
    root, weight, path, _ = bundle
    load = Mock()
    monkeypatch.setattr(utils, "transformers", SimpleNamespace(
        M2M100Tokenizer=SimpleNamespace(from_pretrained=load), NllbTokenizerFast=SimpleNamespace(from_pretrained=load)))
    (path / "tokenizer_config.json").unlink()
    with pytest.raises(utils.MissingCTranslate2Tokenizer):
        utils.downloadCTranslate2Tokenizer(root, weight)
    load.assert_not_called()
    response, config, _ = enable_translation(root, weight, monkeypatch)
    # This one the review can repair: it opens.
    assert response["result"]["error_code"] == "TRANSLATION_MODEL_MISSING"
    assert not config.ENABLE_TRANSLATION
