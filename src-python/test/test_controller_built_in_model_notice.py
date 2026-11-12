"""The startup notice about missing built-in models is for the engines in use."""
from types import SimpleNamespace

import pytest

import controller as controller_module
from controller import Controller


@pytest.mark.parametrize("translation,transcription,ctranslate2,whisper,missing", [
    # A fresh install: the default translator is the built-in one, nothing downloaded.
    ("CTranslate2", None, False, False, True),
    # The translation model is there and transcription uses Google: nothing in use is missing.
    ("CTranslate2", "Google", True, False, False),
    # External services for both: the built-in models are not used.
    ("DeepL_API", "Google", False, False, False),
    ("DeepL_API", None, False, False, False),
    # Whisper is selected without its model.
    ("DeepL_API", "Whisper", False, False, True),
    ("CTranslate2", "Whisper", True, False, True),
    ("CTranslate2", "Whisper", False, True, True),
    ("CTranslate2", "Whisper", True, True, False),
])
def test_only_a_model_the_selected_engines_need_counts_as_missing(
        monkeypatch, translation, transcription, ctranslate2, whisper, missing):
    monkeypatch.setattr(controller_module, "config", SimpleNamespace(
        SELECTED_TAB_NO="2",
        # Another tab still on the default must not bring the notice back.
        SELECTED_TRANSLATION_ENGINES={"1": "CTranslate2", "2": translation, "3": "CTranslate2"},
        SELECTED_TRANSCRIPTION_ENGINE=transcription,
    ))
    assert Controller._missingBuiltInModelInUse(ctranslate2, whisper) is missing
