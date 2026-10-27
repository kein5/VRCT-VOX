"""Execute the real Controller with injected OS/model services, not a GPU.

This validates pipeline contracts; it is not a Windows runtime or VRChat E2E.
"""
import importlib.util
import sys
from threading import Event, Thread
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import AudioFrame
from test_scheduler import Sink, until


@pytest.fixture
def controller_module(monkeypatch):
    # Stub only unrelated services at the import boundary. Controller and
    # MessageDirectionSpec are the production sources, with no AST rewrites.
    stubs = {
        "model": {"model": MagicMock(), "SETUP_LAUNCHED": 1, "SETUP_DOWNLOAD_FAILED": 2, "SETUP_VERIFY_FAILED": 3},
        "models.translation.translation_providers": {"TRANSLATION_PROVIDER_REGISTRY": {}, "CONNECTION_PROVIDER_REGISTRY": {}},
        "models.transcription.transcription_openai_compatible": {"TRANSCRIPTION_MODEL_KEYWORDS": {}, "TRANSCRIPTION_API_ENGINES": ()},
        "models.overlay.overlay_tooltip": {"validate_tooltip": MagicMock()},
        "models.overlay.overlay": {name: MagicMock() for name in ("PANEL_ANCHORS", "computeVrLayout", "clampPanelSize", "mirrorHandPosition")},
    }
    for name, attrs in stubs.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("voice_test_controller", Path(__file__).parents[2] / "src-python/controller.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.config = SimpleNamespace(
        VOICE_SETTINGS=VoiceSettings().to_dict(), ENABLE_TRANSLATION=False,
        SELECTED_YOUR_LANGUAGES={"1": {"1": {"language": "Japanese", "enable": True}}},
        SELECTED_TARGET_LANGUAGES={"1": {"1": {"language": "English", "enable": True},
                                             "2": {"language": "Japanese", "enable": True}}},
        SELECTED_TAB_NO="1", SELECTED_TAB_TARGET_LANGUAGES_NO_LIST=["1", "2"],
        CONVERT_MESSAGE_TO_HIRAGANA=False, CONVERT_MESSAGE_TO_ROMAJI=False,
        SEND_MESSAGE_TO_VRC=True, SEND_ONLY_TRANSLATED_MESSAGES=False,
        OVERLAY_LARGE_LOG=False, OVERLAY_SMALL_LOG=False, ENABLE_CLIPBOARD=False,
        LOGGER_FEATURE=False, ENABLE_TRANSCRIPTION_RECEIVE=True, SEND_RECEIVED_MESSAGE_TO_VRC=False,
    )
    module.model.checkWebSocketServerAlive.return_value = True
    module.model.checkKeywords.return_value = False
    module.model.detectRepeatReceiveMessage.return_value = False
    return module


def test_text_to_osc_websocket_history_and_pcm_once(controller_module, pcm_server):
    module = controller_module
    sink = Sink()
    with pcm_server() as (url, requests):
        controller = module.Controller()
        controller.messageFormatter = MagicMock(return_value="こんにちは")
        settings = VoiceSettings(mode="original", output_device="cable", japanese_url=url)
        controller.voice_events = VoiceEventBus(settings, router=AudioRouter(lambda *args: sink))
        try:
            result = controller.chatMessage({"id": "chat-1", "message": "こんにちは"})
            assert result == {"status": 200, "result": {"id": "chat-1", "original": {
                "message": "こんにちは", "transliteration": []}, "translations": []}}
            module.model.oscSendMessage.assert_called_once_with("こんにちは")
            module.model.addTranslationHistory.assert_called_once_with("chat", "こんにちは")
            legacy = module.model.websocketSendMessage.call_args.args[0]
            assert set(legacy) == {"type", "src_languages", "dst_languages", "message", "translation", "transliteration"}
            assert legacy["type"] == "CHAT"
            until(lambda: controller.voice_events.status()["completed"] == 1)
            assert len(requests) == 1
            assert b"".join(sink.data) == b"\x01\x00\x02\x00"
        finally:
            controller.voice_events.close()


def test_off_and_tts_error_preserve_legacy_delivery(controller_module):
    module = controller_module
    controller = module.Controller()
    controller.messageFormatter = MagicMock(return_value="hello")
    assert controller.chatMessage({"id": "x", "message": "hello"})["status"] == 200
    assert controller.voice_events._thread is None
    controller.voice_events.configure(VoiceSettings(mode="original", output_device="cable"))
    controller.voice_events.publish = MagicMock(side_effect=RuntimeError("fault"))
    assert controller.chatMessage({"id": "y", "message": "hello"})["status"] == 200
    assert module.model.oscSendMessage.call_count == 2
    assert module.model.websocketSendMessage.call_count == 2
    controller.voice_events.close()


def test_translated_slot_and_cancellation_during_translation(controller_module):
    module = controller_module
    module.config.ENABLE_TRANSLATION = True
    controller = module.Controller()
    controller.messageFormatter = MagicMock(return_value="text")
    controller.voice_events.configure(VoiceSettings(mode="translated", target_slot="2", output_device="cable"))
    publish = MagicMock(return_value=True)
    controller.voice_events.publish = publish
    module.model.getInputTranslate.return_value = (["hello", "こんにちは"], [True, True])
    controller.chatMessage({"id": "1", "message": "original"})
    event = publish.call_args.args[0]
    assert (event.translated_text, event.target_language) == ("こんにちは", "Japanese")
    generation = controller.voice_events.generation()
    def translate(*args, **kwargs):
        controller.stopVoice()
        return ["hello", "こんにちは"], [True, True]
    module.model.getInputTranslate.side_effect = translate
    controller.chatMessage({"id": "2", "message": "original"})
    assert publish.call_args.kwargs["expected_generation"] == generation
    assert controller.voice_events.generation() != generation
    controller.voice_events.close()


def test_settings_endpoint_invalid_does_not_mutate(controller_module):
    controller = controller_module.Controller()
    assert controller.setVoiceSettings({"mode": "original"})["status"] == 400
    assert controller.voice_events.settings.mode == "off"
    assert controller.setVoiceSettings({"mode": "original", "output_device": "cable"})["status"] == 200
    assert controller_module.config.VOICE_SETTINGS["mode"] == "original"
    assert controller.setVoiceSettings({"mode": "off"})["status"] == 200
    assert controller.voice_events._thread is None
    controller.voice_events.close()


@pytest.mark.parametrize("mode", ["original", "translated"])
def test_original_speaks_before_translation_but_translated_waits(controller_module, mode):
    """Putting both modes after translation must break the original-mode case."""
    module = controller_module
    module.config.ENABLE_TRANSLATION = True
    entered, release, spoken = Event(), Event(), Event()
    sink = Sink()

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            spoken.set()
            yield AudioFrame(b"\x01\x00" * 48, 48000)

    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(2), "test translation not released"
        return ["hello", "こんにちは"], [True, True]

    module.model.getInputTranslate.side_effect = translate
    controller = module.Controller()
    controller.messageFormatter = MagicMock(return_value="text")
    controller.voice_events = VoiceEventBus(
        VoiceSettings(mode=mode, output_device="cable", target_slot="2"),
        provider_factory=Provider, router=AudioRouter(lambda *args: sink))
    result = []
    worker = Thread(target=lambda: result.append(controller.chatMessage({"id": mode, "message": "原文"})))
    worker.start()
    try:
        assert entered.wait(1)
        assert spoken.wait(0.25) is (mode == "original")
        assert not result  # Translation remains blocked while original speech starts.
        release.set()
        worker.join(1)
        assert result[0]["status"] == 200
        until(lambda: controller.voice_events.status()["completed"] == 1)
        assert len(sink.data) == 1
        module.model.addTranslationHistory.assert_called_once_with("chat", "原文")
    finally:
        release.set()
        worker.join(2)
        controller.voice_events.close()


def test_chat_accepted_before_cancel_cannot_speak_later(controller_module):
    """A chat still in Main's queue keeps text delivery but loses old TTS intent."""
    module = controller_module
    controller = module.Controller()
    controller.messageFormatter = MagicMock(return_value="text")
    controller.voice_events.configure(VoiceSettings(mode="original", output_device="cable"))
    old_generation = controller.voice_events.generation()
    controller.stopVoice()
    try:
        result = controller.chatMessage({"id": "old", "message": "queued",
                                         "_voice_generation": old_generation})
        assert result["status"] == 200
        assert controller.voice_events.status()["accepted"] == 0
        module.model.addTranslationHistory.assert_called_once_with("chat", "queued")
        assert controller.voice_events._thread is None
    finally:
        controller.voice_events.close()


@pytest.mark.parametrize('action', ['cancel', 'same-settings'])
def test_blocked_translation_never_revives_old_speech_and_new_chat_still_works(controller_module, action):
    module = controller_module
    module.config.ENABLE_TRANSLATION = True
    entered, release = Event(), Event()
    sink = Sink()

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            yield AudioFrame(b'\x01\x00' * 48, 48000)

    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return ['hello', 'こんにちは'], [True, True]

    module.model.getInputTranslate.side_effect = translate
    controller = module.Controller()
    controller.messageFormatter = MagicMock(return_value='text')
    settings = VoiceSettings(mode='translated', output_device='cable', target_slot='2')
    controller.voice_events = VoiceEventBus(settings, provider_factory=Provider,
                                          router=AudioRouter(lambda *args: sink))
    worker = Thread(target=lambda: controller.chatMessage({'id': 'old', 'message': 'original'}))
    worker.start()
    try:
        assert entered.wait(1)
        if action == 'cancel':
            controller.stopVoice()
        else:
            assert controller.setVoiceSettings(settings.to_dict())['status'] == 200
        release.set()
        worker.join(1)
        assert not worker.is_alive()
        assert controller.voice_events.status()['accepted'] == 0
        assert controller.chatMessage({'id': 'new', 'message': 'new'})['status'] == 200
        until(lambda: controller.voice_events.status()['completed'] == 1)
        assert len(sink.data) == 1
        assert module.model.addTranslationHistory.call_count == 2
    finally:
        release.set()
        worker.join(2)
        controller.voice_events.close()


def test_existing_message_pipeline_suite_with_injected_services(controller_module, monkeypatch, tmp_path):
    """Reuse upstream assertions unchanged; OS/model services remain injected."""
    import unittest
    from config import config
    controller_module.config = config
    controller_module.model = SimpleNamespace()
    monkeypatch.setattr(config, "_PATH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setitem(sys.modules, "controller", controller_module)
    path = Path(__file__).parents[2] / "src-python/test/test_controller_message_pipeline.py"
    spec = importlib.util.spec_from_file_location("legacy_message_tests", path)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    result = unittest.TestResult()
    try:
        unittest.defaultTestLoader.loadTestsFromModule(legacy).run(result)
        assert result.testsRun > 30
        assert not result.failures and not result.errors, result.failures + result.errors
    finally:
        timer = getattr(config, "_timer", None)
        if timer:
            timer.cancel()
