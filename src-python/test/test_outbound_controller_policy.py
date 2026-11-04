"""Controller/config boundary tests: no services or network requests."""
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as module
from config import Config, ConfigValidationError
from models.legacy_model_consent import legacyModelReview, recordLegacyConsent
from models.network_policy import CUSTOM_URL_KEYS, own_discovery_client


@pytest.mark.parametrize("key", CUSTOM_URL_KEYS)
def test_saved_invalid_endpoint_is_disabled_and_reported(tmp_path, key):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({key: "http://public.example/v1?api_key=secret"}))
    instance = object.__new__(Config)
    instance.init_config()
    instance._PATH_CONFIG = str(path)
    try:
        instance.load_config()
        assert getattr(instance, key) == ""
        assert instance.INVALID_SAVED_API_URLS == [key]
        assert json.loads(path.read_text())[key] == ""
        with pytest.raises(ConfigValidationError):
            setattr(instance, key, "https://user:password@other.example")
        assert getattr(instance, key) == ""
        setattr(instance, key, "http://192.168.1.2/v1")
        assert getattr(instance, key) == "http://192.168.1.2/v1"
    finally:
        timer = getattr(instance, "_timer", None)
        if timer:
            timer.cancel()


@pytest.mark.parametrize("method,key,code", [
    ("setCustomWhisperURL", "TRANSCRIPTION_CUSTOM_URL", "CONNECTION_TRANSCRIPTION_CUSTOM_URL_INVALID"),
    ("setTranslatorLMStudioURL", "LMSTUDIO_URL", "CONNECTION_LMSTUDIO_URL_INVALID"),
    ("setOpenAICompatibleURL", "OPENAI_COMPATIBLE_URL", "CONNECTION_OPENAI_COMPATIBLE_URL_INVALID"),
])
def test_url_setters_reject_before_old_key_can_leave(monkeypatch, method, key, code):
    backend = Mock()
    config = SimpleNamespace(**{key: "https://old.example/v1"})
    monkeypatch.setattr(module, "model", backend)
    monkeypatch.setattr(module, "config", config)
    controller = module.Controller.__new__(module.Controller)
    result = getattr(controller, method)("http://new-public.example/v1")
    assert result["status"] == 400 and result["result"]["error_code"] == code
    assert result["result"]["data"] == "https://old.example/v1"
    assert backend.mock_calls == []


@pytest.mark.parametrize("enabled,missing,consent,probe_result,expected", [
    (False, True, "matching", True, 0), (True, False, "matching", True, 0),
    (True, True, "absent", True, 0), (True, True, "stale", True, 0),
    (True, True, "matching", True, 1), (True, True, "matching", False, 1),
])
def test_startup_probes_only_when_consented_download_will_run(monkeypatch, enabled, missing, consent, probe_result, expected):
    backend = Mock()
    backend.checkTranslatorCTranslate2ModelWeight.return_value = not missing
    backend.checkTranscriptionWhisperModelWeight.return_value = True
    config = SimpleNamespace(AUTO_DOWNLOAD_MODELS=enabled, CTRANSLATE2_WEIGHT_TYPE="m2m100_418M-ct2-int8",
                             WHISPER_WEIGHT_TYPE="base", LEGACY_MODEL_DOWNLOAD_CONSENTS={})
    if consent != "absent":
        request = {"weight_type": config.CTRANSLATE2_WEIGHT_TYPE, "consent": True,
                   "manifest_version": legacyModelReview("ctranslate2", config.CTRANSLATE2_WEIGHT_TYPE)["manifest_version"]}
        recordLegacyConsent(config, "ctranslate2", request)
        if consent == "stale":
            config.LEGACY_MODEL_DOWNLOAD_CONSENTS = {"ctranslate2": {config.CTRANSLATE2_WEIGHT_TYPE: "stale"}}
    monkeypatch.setattr(module, "model", backend)
    monkeypatch.setattr(module, "config", config)
    monkeypatch.setattr(module, "removeLog", lambda: None)
    probe = Mock(return_value=probe_result)
    monkeypatch.setattr(module, "isConnectedNetwork", probe)
    controller = module.Controller.__new__(module.Controller)
    controller._model = backend
    controller.startWatchdog = Mock()
    controller.initializationProgress = Mock()
    controller.run = Mock()
    controller.run_mapping = {"connected_network": "/run/connected_network",
                              "error_ctranslate2_weight": "/run/error_ctranslate2_weight"}
    controller.downloadCtranslate2Weight = Mock()
    controller.downloadWhisperWeight = Mock()
    controller._legacyDownloads = Mock(return_value=SimpleNamespace(stop=lambda *_: False))
    class FinishedWeights(Exception):
        pass
    controller.enableAiModels = controller.disableAiModels = Mock(side_effect=FinishedWeights)
    with pytest.raises(FinishedWeights):
        controller.init()
    assert probe.call_count == expected
    assert controller.downloadCtranslate2Weight.call_count == int(bool(expected and probe_result))
    controller.run.assert_any_call(200, "/run/connected_network", None)
    if expected:
        controller.run.assert_any_call(200, "/run/connected_network", probe_result)


def test_startup_budget_closes_abandoned_worker_client(monkeypatch):
    entered, closed, finished = Event(), Event(), Event()
    class Client:
        def close(self):
            closed.set()
    def check(engine):
        own_discovery_client(Client())
        entered.set()
        assert closed.wait(2)
        finished.set()
        return engine, True
    monkeypatch.setattr(module, "_ENGINE_CHECK_BUDGET_SEC", 0.05)
    try:
        results = module._runEngineChecks(check, ["blocked"], "test")
    except TimeoutError:
        # The worker can observe its own deadline before as_completed times out.
        results = {}
    assert entered.is_set() and closed.is_set() and finished.wait(1)
    assert results == {}
