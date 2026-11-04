"""CTranslate2 availability and loading require the pinned complete bundle."""
import hashlib
from unittest.mock import Mock

import pytest

from models.translation import translation_utils as utils
from models.translation import translation_translator as translator


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    weight = "m2m100_418M-ct2-int8"
    bodies = {"model.bin": b"weights", "vocab.json": b"vocabulary", "sentencepiece.bpe.model": b"spm"}
    repo = utils.ctranslate2_weights[weight]["hf_repo"]
    monkeypatch.setitem(utils.MODEL_PINS, repo, {"revision": "b" * 40, "files": {
        name: (len(body), hashlib.sha256(body).hexdigest()) for name, body in bodies.items()
    }})
    return tmp_path, weight, bodies


def write(path, bodies):
    path.mkdir(parents=True)
    for name, body in bodies.items():
        (path / name).write_bytes(body)


@pytest.mark.parametrize("new_state", ["empty", "mismatch", "complete"])
def test_migration_conflict_keeps_old_copy_and_resolves_verified_model(pinned, new_state):
    root, weight, bodies = pinned
    old = root / "weights/ctranslate2/m2m100_418M"
    new = old.with_name(weight)
    write(old, bodies)
    write(new, bodies if new_state == "complete" else
          {"model.bin": b"user data"} if new_state == "mismatch" else {})
    utils.backwardCompatibleRenameWeightsDir(root)
    assert old.exists() and new.exists()
    assert (old / "model.bin").read_bytes() == bodies["model.bin"]
    assert utils.resolveCTranslate2Weight(root, weight) == (new if new_state == "complete" else old)
    assert utils.hasCTranslate2WeightFile(root, weight)
    end = Mock()
    assert utils.downloadCTranslate2Weight(root, weight, end_callback=end)
    end.assert_called_once()


def test_migration_moves_only_a_verified_legacy_directory(pinned):
    root, weight, bodies = pinned
    old = root / "weights/ctranslate2/m2m100_418M"
    write(old, {"model.bin": b"user data"})
    utils.backwardCompatibleRenameWeightsDir(root)
    assert old.exists() and not old.with_name(weight).exists()
    for name, body in bodies.items():
        (old / name).write_bytes(body)
    utils.backwardCompatibleRenameWeightsDir(root)
    assert not old.exists() and utils.resolveCTranslate2Weight(root, weight) == old.with_name(weight)


def test_mismatch_is_not_present_and_load_does_not_call_native_parser(pinned, monkeypatch):
    root, weight, _ = pinned
    path = root / "weights/ctranslate2" / weight
    write(path, {"model.bin": b"unverified"})
    loader = Mock()
    monkeypatch.setattr(translator, "ctranslate2", loader)
    monkeypatch.setattr(translator, "transformers", Mock())
    assert not utils.hasCTranslate2WeightFile(root, weight)
    with pytest.raises(utils.MissingCTranslate2Tokenizer):
        translator.Translator().changeCTranslate2Model(root, weight, compute_type="int8")
    loader.Translator.assert_not_called()
    assert (path / "model.bin").read_bytes() == b"unverified"
