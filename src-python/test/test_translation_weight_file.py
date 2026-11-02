"""hasCTranslate2WeightFile looks for model.bin without loading the model."""

from models.translation import translation_utils


def test_reports_whether_model_bin_is_on_disk(tmp_path, monkeypatch):
    weight_type = "m2m100_418M-ct2-int8"
    directory = tmp_path / "weights" / "ctranslate2" / translation_utils.ctranslate2_weights[weight_type]["directory_name"]
    assert translation_utils.hasCTranslate2WeightFile(str(tmp_path), weight_type) is False
    directory.mkdir(parents=True)
    assert translation_utils.hasCTranslate2WeightFile(str(tmp_path), weight_type) is False
    (directory / "model.bin").write_bytes(b"")
    # The check never loads the model, so a broken file still counts as present.
    monkeypatch.setattr(translation_utils, "ctranslate2", None)
    assert translation_utils.hasCTranslate2WeightFile(str(tmp_path), weight_type) is True
