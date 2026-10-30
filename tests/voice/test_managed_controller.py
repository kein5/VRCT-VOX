import sys
from threading import Event, Thread
from unittest.mock import MagicMock

import pytest

from models.audio_routing.mute_state import MuteState
from models.tts.settings import VoiceSettings
from test_controller_integration import controller_module  # noqa: F401
from test_managed_route import Gate, ready


@pytest.fixture
def app(controller_module, monkeypatch):  # noqa: F811
    gate = Gate()
    monkeypatch.setattr(controller_module, 'PipeWireGate', lambda: gate)
    controller = controller_module.Controller()
    controller.messageFormatter = MagicMock(return_value='text')
    yield controller, gate, controller_module
    gate.missing = gate.fail = False
    controller.voice_route.close()
    controller.voice_events.close()


def test_mute_survives_settings_stop_and_controller_recreation(app):
    controller, gate, module = app
    assert controller.muteVoice()['result']['requested_muted']
    ready(controller.voice_route)
    assert controller.setVoiceSettings({'mode': 'original', 'output_device': 'cable'})['status'] == 200
    controller.stopVoice()
    assert controller.voice_events.status()['muted']
    assert controller.chatMessage({'id': 'muted', 'message': 'hello'})['status'] == 200
    assert controller.voice_events.status()['accepted'] == 0
    module.model.oscSendMessage.assert_called_once()
    second = module.Controller()
    try:
        assert second.getVoiceRoute()['result']['requested_muted']
        assert second.voice_events.status()['muted']
    finally:
        second.voice_route.close()
        second.voice_events.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="managed route is Linux only")
def test_managed_routing_preserves_external_selection_and_mutes_on_start(app):
    controller, gate, module = app
    settings = VoiceSettings(mode='original', routing='managed', output_device='saved-cable')
    assert controller.setVoiceSettings(settings.to_dict())['status'] == 200
    ready(controller.voice_route)
    assert gate.muted
    assert controller.voice_events.settings.playback_device == 'vrct.managed.tts'
    assert controller.getVoiceSettings()['result']['output_device'] == 'saved-cable'
    assert controller.resumeVoice()['status'] == 200
    ready(controller.voice_route)
    assert not gate.muted
    second = module.Controller()
    try:
        ready(second.voice_route)
        assert gate.muted and second.voice_events.status()['muted']
    finally:
        second.voice_route.close()
        second.voice_events.close()


def test_translated_chat_pending_across_mute_resume_never_speaks(app):
    controller, gate, module = app
    module.config.ENABLE_TRANSLATION = True
    controller.setVoiceSettings({'mode': 'translated', 'output_device': 'cable'})
    entered, release = Event(), Event()
    def translate(*args, **kwargs):
        entered.set()
        release.wait(2)
        return ['hello', 'hello'], [True, True]
    module.model.getInputTranslate.side_effect = translate
    thread = Thread(target=controller.chatMessage, args=({'id': 'late', 'message': 'hello'},))
    thread.start()
    try:
        assert entered.wait(1)
        controller.muteVoice()
        ready(controller.voice_route)
        controller.resumeVoice()
        ready(controller.voice_route)
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert controller.voice_events.status()['accepted'] == 0
    module.model.oscSendMessage.assert_called_once()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="managed route is Linux only")
def test_resume_failure_and_unknown_os_state_are_not_success(app):
    controller, gate, module = app
    gate.missing = True
    controller.setVoiceSettings({'routing': 'managed'})
    from test_scheduler import until
    until(lambda: controller.voice_route.status()['error'])
    result = controller.resumeVoice()
    assert result['status'] == 409
    assert controller.getVoiceRoute()['result']['observed_muted'] is None


def test_legacy_start_does_not_touch_os_gate(controller_module, monkeypatch):  # noqa: F811
    gate = MagicMock()
    monkeypatch.setattr(controller_module, 'PipeWireGate', lambda: gate)
    controller = controller_module.Controller()
    try:
        assert not controller.voice_events.status()['muted']
        assert not gate.mock_calls
    finally:
        controller.voice_route.close()
        controller.voice_events.close()


def test_corrupt_persisted_state_fails_closed(controller_module, monkeypatch):  # noqa: F811
    from pathlib import Path
    path = Path(controller_module.config._PATH_CONFIG).with_name('voice_mute_state.json')
    path.write_text('broken')
    monkeypatch.setattr(controller_module, 'PipeWireGate', Gate)
    controller = controller_module.Controller()
    try:
        assert controller.voice_events.status()['muted']
        assert controller.resumeVoice()['status'] == 409
        controller.muteVoice()
        ready(controller.voice_route)
        assert MuteState(path).read() is True
    finally:
        controller.voice_route.close()
        controller.voice_events.close()


def test_managed_selection_rejected_on_windows(app, monkeypatch):
    controller, gate, module = app
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    assert controller.setVoiceSettings({'routing': 'managed'})['status'] == 400
    assert controller.voice_events.settings.routing == 'external'
