"""Exercise Controller.init's real download decisions with external services injected."""
# ruff: noqa: F811 -- imported pytest fixture is intentionally injected by name
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_controller_integration import controller_module  # noqa: F401
from models.legacy_model_consent import recordLegacyConsent, legacyModelReview


class ReachedEngineSetup(Exception):
    pass


def test_policy_can_be_read_enabled_and_disabled_without_downloading(controller_module):
    module = controller_module
    module.config.AUTO_DOWNLOAD_MODELS = False
    controller = module.Controller.__new__(module.Controller)
    assert controller.getAutoDownloadModels() == {"status": 200, "result": False}
    assert controller.setEnableAutoDownloadModels() == {"status": 200, "result": True}
    assert controller.getAutoDownloadModels()["result"] is True
    assert controller.setDisableAutoDownloadModels() == {"status": 200, "result": False}
    assert not module.model.mock_calls


@pytest.mark.parametrize("enabled,consent,available,reachable,expected", [
    (False, "absent", False, True, []),
    (False, "absent", True, True, []),
    (True, "absent", False, True, []),
    (True, "matching", False, True, ["translation", "whisper", "translation", "whisper"]),
    (True, "matching", True, True, []),
    (False, "matching", False, True, []),
    (True, "stale", False, True, []),
    (True, "matching", False, False, []),
])
def test_startup_download_requires_explicit_consent(controller_module, monkeypatch,
                                                  enabled, consent, available, reachable, expected):
    module = controller_module
    monkeypatch.setattr(module, "config", SimpleNamespace(
        AUTO_DOWNLOAD_MODELS=enabled, CTRANSLATE2_WEIGHT_TYPE="m2m100_418M-ct2-int8",
        WHISPER_WEIGHT_TYPE="base", LEGACY_MODEL_DOWNLOAD_CONSENTS={}))
    if consent != "absent":
        for kind, weight in [("whisper", "base"), ("ctranslate2", "m2m100_418M-ct2-int8")]:
            recordLegacyConsent(module.config, kind, {"weight_type": weight, "consent": True,
                "manifest_version": legacyModelReview(kind, weight)["manifest_version"]})
        if consent == "stale":
            module.config.LEGACY_MODEL_DOWNLOAD_CONSENTS = {
                key: "stale" for key in module.config.LEGACY_MODEL_DOWNLOAD_CONSENTS}
    external = MagicMock()
    external.checkTranslatorCTranslate2ModelWeight.return_value = available
    external.checkTranscriptionWhisperModelWeight.return_value = available
    monkeypatch.setattr(module, "model", external)
    probe = MagicMock(return_value=reachable)
    monkeypatch.setattr(module, "isConnectedNetwork", probe)
    monkeypatch.setattr(module, "removeLog", lambda: None)
    controller = module.Controller.__new__(module.Controller)
    controller._model = external
    controller.run_mapping = {f"error_{kind}_weight": f"/run/error_{kind}_weight" for kind in ("whisper", "ctranslate2")}
    controller.run_mapping["connected_network"] = "/run/connected_network"
    controller.run = MagicMock()
    controller.startWatchdog = lambda: None
    controller.initializationProgress = lambda progress: None
    requests = []
    controller.downloadCtranslate2Weight = lambda *args: requests.append("translation")
    controller.downloadWhisperWeight = lambda *args: requests.append("whisper")

    def finished():
        raise ReachedEngineSetup()

    controller.disableAiModels = controller.enableAiModels = finished
    with pytest.raises(ReachedEngineSetup):
        controller.init()
    # Independent models may download in either order in the initial threads.
    assert sorted(requests) == sorted(expected)
    should_probe = enabled and consent == "matching" and not available
    if should_probe:
        probe.assert_called_once_with()
    else:
        probe.assert_not_called()
    network_states = [call.args[2] for call in controller.run.call_args_list
                      if call.args[1] == "/run/connected_network"]
    assert network_states == ([None, reachable] if should_probe else [None])
    assert controller._ctranslate2_available_cache is available
    assert controller._whisper_available_cache is available
