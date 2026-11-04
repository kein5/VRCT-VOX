"""Real controller download/startup/shutdown handlers with fake operations only."""
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as module
from models.legacy_model_consent import legacyModelReview
from models.legacy_model_downloads import LegacyDownloads


@pytest.fixture
def app(monkeypatch):
    backend = Mock()
    config = SimpleNamespace(LEGACY_MODEL_DOWNLOAD_CONSENTS={},
        SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT={}, SELECTABLE_WHISPER_WEIGHT_TYPE_DICT={})
    monkeypatch.setattr(module, "model", backend)
    monkeypatch.setattr(module, "config", config)
    controller = module.Controller.__new__(module.Controller)
    controller.legacy_downloads = LegacyDownloads()
    controller.run_mapping = {f"{event}_{kind}_weight": f"/run/{event}_{kind}_weight"
        for kind in ("whisper", "ctranslate2") for event in ("downloaded", "error", "download_progress")}
    controller.run = Mock()
    yield controller, config, backend
    assert controller.legacy_downloads.close()


@pytest.mark.parametrize("kind,weight", [("whisper", "base"), ("ctranslate2", "m2m100_418M-ct2-int8")])
@pytest.mark.parametrize("outcome", ["ready", "already_present", "false", "exception", "verification_exception", "tokenizer_missing"])
def test_every_terminal_path_has_one_weight_and_job_identity(app, kind, weight, outcome):
    controller, config, backend = app
    download = backend.downloadWhisperModelWeight if kind == "whisper" else backend.downloadCTranslate2ModelWeight
    verify = backend.checkTranscriptionWhisperModelWeight if kind == "whisper" else backend.checkTranslatorCTranslate2ModelWeight
    download.return_value = outcome != "false"
    verify.return_value = outcome != "tokenizer_missing"
    if outcome == "exception":
        download.side_effect = OSError("failed transport")
    if outcome == "verification_exception":
        verify.side_effect = ValueError("parser failed")
    method = controller.downloadWhisperWeight if kind == "whisper" else controller.downloadCtranslate2Weight
    response = method({"weight_type": weight, "consent": True,
        "manifest_version": legacyModelReview(kind, weight)["manifest_version"]}, asynchronous=False)
    assert response["status"] == 200
    controller.run.assert_called_once()
    status, endpoint, result = controller.run.call_args.args
    ready = outcome in ("ready", "already_present")
    assert status == (200 if ready else 400)
    assert endpoint == f"/run/{'downloaded' if ready else 'error'}_{kind}_weight"
    data = result if ready else result["data"]
    assert data["weight_type"] == weight
    assert data["job_id"] == response["result"]["job_id"]
    assert data["downloaded"] is ready
    states = config.SELECTABLE_WHISPER_WEIGHT_TYPE_DICT if kind == "whisper" else config.SELECTABLE_CTRANSLATE2_WEIGHT_TYPE_DICT
    assert states[weight] is ready
    backend.downloadCTranslate2ModelTokenizer.assert_not_called()


def test_controller_shutdown_signals_and_joins_before_other_teardown(app):
    controller, _, _ = app
    entered, finished, results = Event(), Event(), []

    def operation(control):
        entered.set()
        assert control.event.wait(2)
        finished.set()
        control.checkpoint()

    thread = controller.legacy_downloads.start("base", operation, lambda *args: results.append(args))
    assert entered.wait(1)

    class AfterLegacyShutdown(Exception):
        pass

    controller._stopServiceForShutdown = Mock(side_effect=AfterLegacyShutdown)
    with pytest.raises(AfterLegacyShutdown):
        controller.shutdown()
    assert finished.is_set() and not thread.is_alive()
    assert results == [(False, "cancelled")]


def test_duplicate_request_returns_identified_busy_and_cannot_start_second_worker(app):
    controller, _, backend = app
    entered = Event()

    def operation(*args, control, **kwargs):
        entered.set()
        assert control.event.wait(2)
        control.checkpoint()

    backend.downloadWhisperModelWeight.side_effect = operation
    request = {"weight_type": "base", "consent": True,
               "manifest_version": legacyModelReview("whisper", "base")["manifest_version"]}
    first = controller.downloadWhisperWeight(request)
    assert entered.wait(1)
    second = controller.downloadWhisperWeight(request)
    assert second["status"] == 400
    assert second["result"]["data"]["reason"] == "download_busy"
    assert second["result"]["data"]["weight_type"] == "base"
    assert second["result"]["data"]["active_job_id"] == first["result"]["job_id"]
    assert backend.downloadWhisperModelWeight.call_count == 1
    assert controller.legacy_downloads.close()
    controller.run.assert_called_once()


@pytest.mark.parametrize("joined", [False, True])
def test_startup_retry_requires_previous_attempt_to_stop_and_join(app, monkeypatch, joined):
    from models.legacy_model_consent import recordLegacyConsent
    controller, config, backend = app
    config.AUTO_DOWNLOAD_MODELS = True
    config.WHISPER_WEIGHT_TYPE = "base"
    config.CTRANSLATE2_WEIGHT_TYPE = "m2m100_418M-ct2-int8"
    for kind, weight in [("whisper", config.WHISPER_WEIGHT_TYPE), ("ctranslate2", config.CTRANSLATE2_WEIGHT_TYPE)]:
        recordLegacyConsent(config, kind, {"weight_type": weight, "consent": True,
            "manifest_version": legacyModelReview(kind, weight)["manifest_version"]})
    monkeypatch.setattr(module, "isConnectedNetwork", lambda: True)
    monkeypatch.setattr(module, "removeLog", lambda: None)
    controller._model = backend
    controller.startWatchdog = controller.connectedNetwork = lambda: None
    controller.initializationProgress = lambda _: None
    backend.checkTranscriptionWhisperModelWeight.return_value = False
    backend.checkTranslatorCTranslate2ModelWeight.return_value = False
    order = []
    controller.downloadWhisperWeight = lambda *_: order.append("start:whisper")
    controller.downloadCtranslate2Weight = lambda *_: order.append("start:ctranslate2")

    def stop(key):
        order.append("stop:" + key[0])
        return joined

    monkeypatch.setattr(controller.legacy_downloads, "stop", stop)

    class ReachedAvailability(Exception):
        pass

    controller.disableAiModels = Mock(side_effect=ReachedAvailability)
    with pytest.raises(ReachedAvailability):
        controller.init()
    assert order == (["start:ctranslate2", "start:whisper", "stop:ctranslate2"] +
                     (["start:ctranslate2"] if joined else []) +
                     ["stop:whisper"] + (["start:whisper"] if joined else []))


def test_shutdown_revokes_then_signals_both_owners_before_any_join(app):
    controller, _, backend = app
    order = []
    backend.message_delivery.revoke.side_effect = lambda source: order.append(source)

    class Owner:
        def __init__(self, name):
            self.name = name

        def request_close(self):
            order.append("signal:" + self.name)

        def close(self):
            assert order[:6] == ["mic", "speaker", "ocr", "chat",
                                 "signal:catalog", "signal:legacy"]
            order.append("join:" + self.name)
            return True

    class AfterDownloadShutdown(Exception):
        pass

    original = controller.legacy_downloads
    controller.model_downloads = Owner("catalog")
    controller.legacy_downloads = Owner("legacy")
    controller._stopServiceForShutdown = Mock(side_effect=AfterDownloadShutdown)
    try:
        with pytest.raises(AfterDownloadShutdown):
            controller.shutdown()
        assert order == ["mic", "speaker", "ocr", "chat",
                         "signal:catalog", "signal:legacy", "join:catalog", "join:legacy"]
    finally:
        controller.legacy_downloads = original
