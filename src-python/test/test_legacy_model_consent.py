"""Offline consent and startup contracts. No download worker or service runs."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import controller as module
from config import Config
from models.builtin_model_pins import MODEL_PINS
from models.legacy_model_consent import (
    legacyModelReview, legacyModelCatalog, recordLegacyConsent, consentedLegacyRequest,
)

MODELS = [("whisper", "base"), ("ctranslate2", "m2m100_418M-ct2-int8"),
          ("ctranslate2", "nllb-200-distilled-600M-ct2-int8")]


def request(kind, weight):
    return {"weight_type": weight, "consent": True,
            "manifest_version": legacyModelReview(kind, weight)["manifest_version"]}


@pytest.fixture
def app(monkeypatch):
    config = SimpleNamespace(LEGACY_MODEL_DOWNLOAD_CONSENTS={},
        CTRANSLATE2_WEIGHT_TYPE=MODELS[2][1], WHISPER_WEIGHT_TYPE="base", AUTO_DOWNLOAD_MODELS=True,
        SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT={}, SELECTABLE_WHISPER_WEIGHT_TYPE_DICT={})
    monkeypatch.setattr(module, "config", config)
    backend = MagicMock()
    monkeypatch.setattr(module, "model", backend)
    controller = module.Controller.__new__(module.Controller)
    controller._model = backend
    controller.run_mapping = {f"error_{kind}_weight": f"/run/error_{kind}_weight" for kind in ("whisper", "ctranslate2")}
    controller.run_mapping["connected_network"] = "/run/connected_network"
    controller.run = MagicMock()
    return controller, config, backend


@pytest.mark.parametrize("kind,weight", MODELS)
@pytest.mark.parametrize("invalid", ["bare", "absent", "false", "truthy", "stale", "other_model", "old_license_flag"])
def test_rejects_before_any_acquisition_or_recording(app, kind, weight, invalid):
    controller, config, backend = app
    data = request(kind, weight)
    if invalid == "bare": data = weight
    elif invalid == "absent": data.pop("consent")
    elif invalid == "false": data["consent"] = False
    elif invalid == "truthy": data["consent"] = "true"
    elif invalid == "stale": data["manifest_version"] = "old"
    elif invalid == "other_model": data["manifest_version"] = legacyModelReview("whisper", "tiny")["manifest_version"]
    else: data = {"weight_type": weight, "accept_non_commercial_license": True}
    method = controller.downloadWhisperWeight if kind == "whisper" else controller.downloadCtranslate2Weight
    response = method(data)
    assert response["status"] == 400
    assert response["result"]["error_code"] == "WEIGHT_DOWNLOAD_CONSENT_REQUIRED"
    assert response["result"]["data"] == {"kind": kind, "weight_type": weight}
    assert backend.mock_calls == []
    assert not hasattr(controller, "legacy_downloads")
    assert config.LEGACY_MODEL_DOWNLOAD_CONSENTS == {}


@pytest.mark.parametrize("kind,weight", MODELS)
@pytest.mark.parametrize("asynchronous", [True, False])
def test_exact_manifest_consent_starts_and_records_without_selecting(app, kind, weight, asynchronous):
    controller, config, backend = app
    selected = config.CTRANSLATE2_WEIGHT_TYPE
    method = controller.downloadWhisperWeight if kind == "whisper" else controller.downloadCtranslate2Weight
    response = method(request(kind, weight), asynchronous=asynchronous)
    assert response["status"] == 200 and response["result"]["weight_type"] == weight
    assert response["result"]["job_id"]
    assert controller._legacyDownloads().wait((kind, weight), timeout=1)
    worker = backend.downloadWhisperModelWeight if kind == "whisper" else backend.downloadCTranslate2ModelWeight
    assert worker.call_args.args[0] == weight
    assert worker.call_args.kwargs["control"] is not None
    backend.downloadCTranslate2ModelTokenizer.assert_not_called()
    assert consentedLegacyRequest(config, kind, weight) == request(kind, weight)
    assert config.CTRANSLATE2_WEIGHT_TYPE == selected
    # Recorded consent authorizes startup, never an unconsented IPC request.
    assert method(weight)["status"] == 400


def test_review_totals_and_restrictions_match_manifest():
    for entry in legacyModelCatalog():
        assert entry["total_bytes"] == sum(size for size, _ in MODEL_PINS[entry["repo"]]["files"].values())
        assert entry["provider"] == entry["repo"].split("/")[0]
        assert entry["tokenizer_size_unknown"] is False
        if "nllb" in entry["weight_type"]:
            assert entry["non_commercial"] is True
            assert entry["license"] == "CC-BY-NC-4.0"
    assert legacyModelReview(*MODELS[1])["total_bytes"] == 499602144


def test_tokenizer_files_are_in_the_reviewed_bundle_without_double_counting():
    entry = legacyModelReview(*MODELS[1])
    tokenizer = entry["tokenizer"]
    assert tokenizer["repo"] == entry["repo"]
    assert tokenizer["revision"] == entry["revision"]
    assert tokenizer["bundled"] is True
    for name, pin in tokenizer["files"].items():
        assert entry["files"][name] == pin
    assert {"vocab.json", "sentencepiece.bpe.model"} <= tokenizer["files"].keys()


def isolated_config(path):
    instance = object.__new__(Config)
    instance.init_config()
    instance._PATH_CONFIG = str(path)
    instance.load_config()
    return instance


@pytest.mark.parametrize("kind,weight", MODELS)
def test_consent_survives_restart_and_manifest_changes_require_review(tmp_path, monkeypatch, kind, weight):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"CTRANSLATE2_WEIGHT_TYPE": MODELS[2][1], "AUTO_DOWNLOAD_MODELS": True}))
    config = isolated_config(path)
    assert config.LEGACY_MODEL_DOWNLOAD_CONSENTS == {}
    assert consentedLegacyRequest(config, kind, weight) is None
    assert recordLegacyConsent(config, kind, request(kind, weight))
    saved = json.loads(path.read_text())["LEGACY_MODEL_DOWNLOAD_CONSENTS"]
    restarted = isolated_config(path)
    assert restarted.LEGACY_MODEL_DOWNLOAD_CONSENTS == saved
    assert restarted.CTRANSLATE2_WEIGHT_TYPE == MODELS[2][1]
    assert consentedLegacyRequest(restarted, kind, weight) == request(kind, weight)
    repo = legacyModelReview(kind, weight)["repo"]
    changed = copy.deepcopy(MODEL_PINS[repo])
    changed["revision"] = "0" * 40
    monkeypatch.setitem(MODEL_PINS, repo, changed)
    assert consentedLegacyRequest(restarted, kind, weight) is None
    assert restarted.LEGACY_MODEL_DOWNLOAD_CONSENTS == saved


def test_tokenizer_revision_and_file_pins_invalidate_consent(monkeypatch):
    config = SimpleNamespace(LEGACY_MODEL_DOWNLOAD_CONSENTS={})
    kind, weight = MODELS[1]
    assert recordLegacyConsent(config, kind, request(kind, weight))
    entry = legacyModelReview(kind, weight)
    changed = copy.deepcopy(MODEL_PINS[entry["repo"]])
    changed["files"]["vocab.json"] = (1, "1" * 64)
    monkeypatch.setitem(MODEL_PINS, entry["repo"], changed)
    assert consentedLegacyRequest(config, kind, weight) is None
    assert recordLegacyConsent(config, kind, request(kind, weight))
    changed = copy.deepcopy(MODEL_PINS[entry["repo"]])
    changed["files"]["model.bin"] = (1, "0" * 64)
    monkeypatch.setitem(MODEL_PINS, entry["repo"], changed)
    assert consentedLegacyRequest(config, kind, weight) is None


@pytest.mark.parametrize("auto,recorded,available", [(True, False, False), (True, True, False),
    (False, True, False), (True, False, True)])
def test_real_startup_skips_or_fetches_including_retry(app, monkeypatch, auto, recorded, available):
    controller, config, backend = app
    config.AUTO_DOWNLOAD_MODELS = auto
    for kind, weight in [("whisper", config.WHISPER_WEIGHT_TYPE), ("ctranslate2", config.CTRANSLATE2_WEIGHT_TYPE)]:
        if recorded: recordLegacyConsent(config, kind, request(kind, weight))
    monkeypatch.setattr(module, "isConnectedNetwork", lambda: True)
    monkeypatch.setattr(module, "removeLog", lambda: None)
    controller.startWatchdog = controller.connectedNetwork = lambda: None
    controller.initializationProgress = lambda _: None
    backend.checkTranslatorCTranslate2ModelWeight.return_value = available
    backend.checkTranscriptionWhisperModelWeight.return_value = available
    class ReachedAvailability(Exception): pass
    def stop(): raise ReachedAvailability()
    controller.disableAiModels = controller.enableAiModels = stop
    with pytest.raises(ReachedAvailability): controller.init()
    expected = 2 if auto and recorded and not available else 0
    assert backend.downloadCTranslate2ModelWeight.call_count == expected
    backend.downloadCTranslate2ModelTokenizer.assert_not_called()
    assert backend.downloadWhisperModelWeight.call_count == expected
    notices = [call for call in controller.run.call_args_list
               if isinstance(call.args[2], dict) and call.args[2].get("error_code") == "WEIGHT_DOWNLOAD_CONSENT_REQUIRED"]
    assert len(notices) == (2 if auto and not recorded and not available else 0)
    for notice in notices:
        assert notice.args[2]["error_code"] == "WEIGHT_DOWNLOAD_CONSENT_REQUIRED"
        assert notice.args[2]["data"]["startup"] is True
