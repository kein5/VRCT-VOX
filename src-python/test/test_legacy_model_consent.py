"""Offline consent and startup contracts. No download worker or service runs."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import controller as module
from config import Config
from models.builtin_model_pins import MODEL_PINS, TOKENIZER_REVISIONS
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
        CTRANSLATE2_WEIGHT_TYPE=MODELS[2][1], WHISPER_WEIGHT_TYPE="base", AUTO_DOWNLOAD_MODELS=True)
    monkeypatch.setattr(module, "config", config)
    backend = MagicMock()
    monkeypatch.setattr(module, "model", backend)
    controller = module.Controller.__new__(module.Controller)
    controller._model = backend
    controller.run_mapping = {f"error_{kind}_weight": f"/run/error_{kind}_weight" for kind in ("whisper", "ctranslate2")}
    controller.run = MagicMock()
    controller.startThreadingDownloadWhisperWeight = MagicMock()
    controller.startThreadingDownloadCtranslate2Weight = MagicMock()
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
    controller.startThreadingDownloadWhisperWeight.assert_not_called()
    controller.startThreadingDownloadCtranslate2Weight.assert_not_called()
    assert config.LEGACY_MODEL_DOWNLOAD_CONSENTS == {}


@pytest.mark.parametrize("kind,weight", MODELS)
@pytest.mark.parametrize("asynchronous", [True, False])
def test_exact_manifest_consent_starts_and_records_without_selecting(app, kind, weight, asynchronous):
    controller, config, backend = app
    selected = config.CTRANSLATE2_WEIGHT_TYPE
    method = controller.downloadWhisperWeight if kind == "whisper" else controller.downloadCtranslate2Weight
    assert method(request(kind, weight), asynchronous=asynchronous) == {"status": 200, "result": True}
    worker = (controller.startThreadingDownloadWhisperWeight if asynchronous else backend.downloadWhisperModelWeight) if kind == "whisper" else (
        controller.startThreadingDownloadCtranslate2Weight if asynchronous else backend.downloadCTranslate2ModelWeight)
    assert worker.call_args.args[0] == weight
    if kind == "ctranslate2": backend.downloadCTranslate2ModelTokenizer.assert_called_once_with(weight)
    assert consentedLegacyRequest(config, kind, weight) == request(kind, weight)
    assert config.CTRANSLATE2_WEIGHT_TYPE == selected
    # Recorded consent authorizes startup, never an unconsented IPC request.
    assert method(weight)["status"] == 400


def test_review_totals_and_restrictions_match_manifest():
    for entry in legacyModelCatalog():
        assert entry["total_bytes"] == sum(size for size, _ in MODEL_PINS[entry["repo"]]["files"].values())
        assert entry["provider"] == entry["repo"].split("/")[0]
        assert entry["tokenizer_size_unknown"] is (entry["kind"] == "ctranslate2")
        if "nllb" in entry["weight_type"]:
            assert entry["non_commercial"] is True
            assert entry["license"] == "CC-BY-NC-4.0"
    assert legacyModelReview(*MODELS[1])["total_bytes"] == 499602144


@pytest.mark.parametrize("matching_revision", [True, False])
def test_tokenizer_bytes_are_included_only_for_the_matching_pinned_revision(monkeypatch, matching_revision):
    # Synthetic metadata only; these are not proposed production file pins.
    entry = legacyModelReview(*MODELS[1])
    tokenizer = entry["tokenizer"]
    monkeypatch.setitem(MODEL_PINS, tokenizer["repo"], {
        "revision": tokenizer["revision"] if matching_revision else "old-revision",
        "files": {"fake-tokenizer.json": (3, "0" * 64)},
    })
    reviewed = legacyModelReview(*MODELS[1])
    assert reviewed["total_bytes"] == entry["total_bytes"] + (3 if matching_revision else 0)
    assert reviewed["tokenizer_size_unknown"] is not matching_revision


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
    monkeypatch.setitem(TOKENIZER_REVISIONS, entry["tokenizer"]["repo"], "1" * 40)
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
    assert backend.downloadCTranslate2ModelTokenizer.call_count == expected
    assert backend.downloadWhisperModelWeight.call_count == expected
    notices = controller.run.call_args_list
    assert len(notices) == (2 if auto and not recorded and not available else 0)
    for notice in notices:
        assert notice.args[2]["error_code"] == "WEIGHT_DOWNLOAD_CONSENT_REQUIRED"
        assert notice.args[2]["data"]["startup"] is True
