"""Independent settings forms merge without touching hardware."""
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import controller as controller_module
from controller import Controller
from models.tts.settings import VoiceSettings


@pytest.mark.parametrize("reverse", [False, True])
def test_voice_forms_preserve_each_others_changes_and_route_effects(monkeypatch, reverse):
    monkeypatch.setattr(controller_module.sys, "platform", "linux")
    config = SimpleNamespace(VOICE_SETTINGS={})
    monkeypatch.setattr(controller_module, "config", config)
    control = object.__new__(Controller)
    control._voice_settings_lock = Lock()
    control.voice_events = SimpleNamespace(settings=VoiceSettings(output_device="output-a", monitor_volume="35"))
    control.voice_events.configure = lambda value: setattr(control.voice_events, "settings", value)
    control.getVoiceSettings = lambda: {"status": 200, "result": control.voice_events.settings.to_dict()}
    control.voice_route = Mock()
    control.direct_voice = Mock()
    control.direct_voice.health.return_value = {"requested": False, "pending": False}
    changes = [{"routing": "managed"}, {"output_device": "output-b"}]
    if reverse:
        changes.reverse()
    for change in changes:
        assert control.setVoiceSettings(change)["status"] == 200
    assert config.VOICE_SETTINGS["routing"] == "managed"
    assert config.VOICE_SETTINGS["output_device"] == "output-b"
    assert config.VOICE_SETTINGS["monitor_volume"] == "35"
    assert [call.args[0] for call in control.voice_route.configure.call_args_list] == ([False, True] if reverse else [True, True])
    assert control.direct_voice.stop.call_count == (1 if reverse else 0)
    control.direct_voice.health.return_value = {"requested": True, "pending": False}
    assert control.setVoiceSettings({"routing": "external"})["status"] == 409
    assert control.setVoiceSettings({"monitor_volume": "101"})["status"] == 400
    assert config.VOICE_SETTINGS["routing"] == "managed"
    assert config.VOICE_SETTINGS["monitor_volume"] == "35"
