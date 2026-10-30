"""Exercise Controller.init's real download decisions with external services injected."""
# ruff: noqa: F811 -- imported pytest fixture is intentionally injected by name
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_controller_integration import controller_module  # noqa: F401


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


@pytest.mark.parametrize("consent,available,expected", [
    (False, False, []),
    (False, True, []),
    (True, False, ["translation", "whisper", "translation", "whisper"]),
])
def test_startup_download_requires_explicit_consent(controller_module, monkeypatch,
                                                  consent, available, expected):
    module = controller_module
    monkeypatch.setattr(module, "config", SimpleNamespace(
        AUTO_DOWNLOAD_MODELS=consent, CTRANSLATE2_WEIGHT_TYPE="test-translation",
        WHISPER_WEIGHT_TYPE="test-whisper"))
    external = MagicMock()
    external.checkTranslatorCTranslate2ModelWeight.return_value = available
    external.checkTranscriptionWhisperModelWeight.return_value = available
    monkeypatch.setattr(module, "model", external)
    monkeypatch.setattr(module, "isConnectedNetwork", lambda: True)
    monkeypatch.setattr(module, "removeLog", lambda: None)
    controller = module.Controller.__new__(module.Controller)
    controller._model = external
    controller.startWatchdog = lambda: None
    controller.connectedNetwork = lambda: None
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
    assert controller._ctranslate2_available_cache is available
    assert controller._whisper_available_cache is available
