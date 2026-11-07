"""Local model replacement and message snapshots, without model downloads."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as controller_module
import model as model_module
from models.translation import translation_translator as module
from models.translation.translation_languages import loadTranslationLanguages
from test_translation_translator_ctranslate2 import FakeHypothesis, FakeTokenizer


M2M = "m2m100_418M-ct2-int8"
M2M_LARGE = "m2m100_1.2B-ct2-int8"
NLLB = "nllb-200-distilled-600M-ct2-int8"


@pytest.fixture
def local_models(monkeypatch, tmp_path):
    loadTranslationLanguages(str(Path(__file__).resolve().parents[2]))
    state = SimpleNamespace(live=[], loads=[], calls=[], beam_sizes=[], fail=False)

    class Tokenizer(FakeTokenizer):
        def __init__(self, weight):
            super().__init__()
            self.weight = weight
            self.lang_code_to_token = {"ja": "__ja__"}

        def encode(self, message, **kwargs):
            assert self.src_lang == ("eng_Latn" if self.weight == NLLB else "en")
            return super().encode(message, **kwargs)

    class Engine:
        def __init__(self, weight, **kwargs):
            # One model fits; two simultaneous native allocations do not.
            if state.live:
                raise RuntimeError("overlapping model allocations")
            if state.fail:
                raise RuntimeError("allocation failed")
            self.weight = weight
            self.loaded = True
            state.live.append(self)
            state.loads.append((weight, kwargs))

        def unload_model(self):
            state.live.remove(self)
            self.loaded = False

        def translate_batch(self, sources, target_prefix, **kwargs):
            assert self.loaded
            assert target_prefix == [["jpn_Jpan" if self.weight == NLLB else "__ja__"]]
            state.calls.append(self.weight)
            state.beam_sizes.append(kwargs.get("beam_size"))
            return [FakeHypothesis([target_prefix[0][0], self.weight, "</s>"])]

    monkeypatch.setattr(module, "ctranslate2", SimpleNamespace(Translator=Engine))
    monkeypatch.setattr(module, "transformers", object())
    monkeypatch.setattr(module, "resolveCTranslate2Weight", Mock(side_effect=lambda root, weight: weight))
    monkeypatch.setattr(module, "downloadCTranslate2Tokenizer", Mock(side_effect=lambda root, weight: Tokenizer(weight)))
    translator = module.Translator()
    translator.changeCTranslate2Model(str(tmp_path), M2M, device="cuda", device_index=1, compute_type="int8")
    state.translator = translator
    state.root = str(tmp_path)
    return state


def translate(translator, weight):
    return translator.translate("CTranslate2", weight, "English", "Japanese", "Japan", "hello")


@pytest.mark.parametrize("weight,beam_size", [(M2M, 5), (M2M_LARGE, 5), (NLLB, None)])
def test_m2m100_uses_the_beam_size_of_its_generation_config(local_models, weight, beam_size):
    assert translate(local_models.translator, weight) == weight
    assert local_models.beam_sizes == [beam_size]


@pytest.mark.parametrize("weight", [NLLB, M2M_LARGE])
def test_enabled_weight_selection_loads_matching_model(local_models, monkeypatch, weight):
    translator = local_models.translator
    cfg = SimpleNamespace(CTRANSLATE2_WEIGHT_TYPE=M2M, ENABLE_TRANSLATION=True)
    backend = Mock()
    backend.setChangedTranslatorParameters.side_effect = translator.setChangedTranslatorParameters
    monkeypatch.setattr(controller_module, "config", cfg)
    monkeypatch.setattr(controller_module, "model", backend)
    app = controller_module.Controller.__new__(controller_module.Controller)
    app.updateTranslationEngineAndEngineList = Mock()
    response = app.setCtranslate2WeightType({"weight_type": weight, "accept_non_commercial_license": True})
    assert response == {"status": 200, "result": weight}
    assert cfg.ENABLE_TRANSLATION
    assert translate(translator, weight) == weight
    assert local_models.calls == [weight]
    assert local_models.loads[-1][1]["device_index"] == 1


def test_queued_snapshot_can_use_previous_weight_after_switch(local_models):
    translator = local_models.translator
    assert translate(translator, NLLB) == NLLB
    assert translate(translator, M2M) == M2M
    assert translate(translator, NLLB) == NLLB
    assert local_models.calls == [NLLB, M2M, NLLB]


def test_concurrent_weight_snapshots_keep_matching_tokenizers(local_models):
    weights = [NLLB, M2M, M2M_LARGE, NLLB] * 3
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda weight: translate(local_models.translator, weight), weights))
    assert results == weights


def test_replacement_releases_old_allocation_before_constructor(local_models):
    translator = local_models.translator
    old_model = translator.ctranslate2_translator
    translator.changeCTranslate2Model(local_models.root, NLLB, device="cuda", compute_type="int8")
    assert not old_model.loaded
    assert translator.isLoadedCTranslate2Model()
    assert len(local_models.live) == 1
    assert translate(translator, NLLB) == NLLB


def test_failed_allocation_leaves_no_model_and_retry_succeeds(local_models):
    translator = local_models.translator
    local_models.fail = True
    with pytest.raises(RuntimeError, match="allocation failed"):
        translator.changeCTranslate2Model(local_models.root, NLLB, device="cuda", compute_type="int8")
    assert not local_models.live
    assert not translator.isLoadedCTranslate2Model()
    assert translator.ctranslate2_translator is None
    assert translator.ctranslate2_tokenizer is None
    assert translator._ctranslate2_model_parameters is None
    local_models.fail = False
    translator.changeCTranslate2Model(local_models.root, NLLB, device="cuda", compute_type="int8")
    assert translate(translator, NLLB) == NLLB


@pytest.mark.parametrize("failure", ["weight", "tokenizer", "compute"])
def test_preflight_failure_preserves_valid_old_model(local_models, monkeypatch, failure):
    translator = local_models.translator
    old_model = translator.ctranslate2_translator
    old_tokenizer = translator.ctranslate2_tokenizer
    if failure == "weight":
        monkeypatch.setattr(module, "resolveCTranslate2Weight", Mock(return_value=None))
    elif failure == "tokenizer":
        monkeypatch.setattr(module, "downloadCTranslate2Tokenizer", Mock(side_effect=RuntimeError("tokenizer")))
    else:
        monkeypatch.setattr(module, "getBestComputeType", Mock(side_effect=RuntimeError("compute")))
    with pytest.raises(Exception):
        translator.changeCTranslate2Model(local_models.root, NLLB)
    assert translator.isLoadedCTranslate2Model()
    assert translator.ctranslate2_translator is old_model
    assert translator.ctranslate2_tokenizer is old_tokenizer
    assert translate(translator, M2M) == M2M
    # Failure to prepare NLLB must not send its language codes to M2M100.
    if failure != "compute":
        assert translate(translator, NLLB) is False
    assert local_models.calls == [M2M]


@pytest.mark.parametrize("dependency", ["ctranslate2", "transformers"])
def test_missing_runtime_keeps_translation_disabled(monkeypatch, tmp_path, dependency):
    translator = module.Translator()
    monkeypatch.setattr(module, "ctranslate2", Mock())
    monkeypatch.setattr(module, "transformers", Mock())
    monkeypatch.setattr(module, dependency, None)
    resolver = Mock()
    monkeypatch.setattr(module, "resolveCTranslate2Weight", resolver)
    backend = Mock()
    backend.isLoadedCTranslate2Model.side_effect = translator.isLoadedCTranslate2Model
    backend.hasTranslatorCTranslate2ModelWeightFile.return_value = True
    backend.detectVRAMError.return_value = (False, "")
    backend.changeTranslatorCTranslate2Model.side_effect = lambda: translator.changeCTranslate2Model(str(tmp_path), M2M)
    monkeypatch.setattr(controller_module, "model", backend)
    cfg = SimpleNamespace(ENABLE_TRANSLATION=False, SELECTED_TAB_NO="1",
                          SELECTED_TRANSLATION_ENGINES={"1": "CTranslate2"}, CTRANSLATE2_WEIGHT_TYPE=M2M)
    monkeypatch.setattr(controller_module, "config", cfg)
    app = controller_module.Controller.__new__(controller_module.Controller)
    response = app.setEnableTranslation()
    assert response["result"]["error_code"] == "TRANSLATION_MODEL_LOAD_FAILED"
    assert response["result"]["data"] is False
    assert not cfg.ENABLE_TRANSLATION
    assert not translator.isLoadedCTranslate2Model()
    backend.setChangedTranslatorParameters.assert_not_called()
    resolver.assert_not_called()


@pytest.mark.parametrize("oversized_input", [True, False])
def test_truncation_returns_original_with_failure(local_models, monkeypatch, oversized_input):
    translator = local_models.translator
    message = "x" * 1025 if oversized_input else "hello"
    engine = translator.ctranslate2_translator
    engine.translate_batch = Mock(return_value=[FakeHypothesis(["__ja__", *(["x"] * 255)])])
    subject = object.__new__(model_module.Model)
    subject.translator = translator
    subject.ensure_initialized = Mock()
    subject.getTranslationHistory = Mock(return_value=[])
    monkeypatch.setattr(model_module, "sleep", lambda _: None)
    result = subject.getTranslate("CTranslate2", "English", "Japanese", "Japan", message,
                                  weight_type=M2M, with_provenance=True)
    assert result == (message, False, "failed")
    if oversized_input:
        engine.translate_batch.assert_not_called()
