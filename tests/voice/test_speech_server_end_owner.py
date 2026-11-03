"""Terminal callbacks own a server run and its TTS dependency, never a later ON.

Real controller, hub and bus; server processes, HTTP and audio are all fakes.
"""
# ruff: noqa: F811 -- pytest uses imported fixtures by name.
from contextlib import contextmanager
from threading import Event
from unittest.mock import MagicMock, call

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.voice_events import AudioFrame
from test_controller_integration import controller_module  # noqa: F401
from test_realtime_controls import app  # noqa: F401
from test_scheduler import Sink, event, until
from test_speech_server_controls import owned, run_server  # noqa: F401
from test_tts_toggle_server import enable


@pytest.fixture
def lifecycle(app, owned, monkeypatch):
    c, m, _ = app
    c.setSpeechServerSettings(owned[0])
    monkeypatch.setattr(m.SpeechCppTTS, 'check_health', lambda self: None)
    c.direct_voice.stop = MagicMock()
    return c, m, owned[1]


def configure(c, server='bundled'):
    assert c.setVoiceSettings(dict(mode='original', output_device='cable',
        japanese_server=server, japanese_url='http://127.0.0.1:8080'))['status'] == 200


@contextmanager
def utterance(c):
    entered, release = Event(), Event()
    tokens, sink = [], Sink()

    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            tokens.append(token)
            entered.set()
            assert release.wait(2), 'test did not release the fake utterance'
            token.check()
            yield AudioFrame(b'\x01\x00' * 48, 48000)

    c.voice_events.provider_factory = Provider
    c.voice_events.router = AudioRouter(lambda *args: sink)
    assert c.voice_events.publish(event('active'))
    try:
        assert entered.wait(1)
        yield tokens[0], sink
    finally:
        release.set()
        until(lambda: not c.voice_events.status()['active'])


@pytest.mark.parametrize('ending', ['stop', 'natural'])
def test_old_end_leaves_new_external_tts_and_utterance_alive(lifecycle, ending):
    c, _, made = lifecycle
    configure(c)
    run_server(c, 'japanese')  # Settings owns this run, not the TTS toggle.
    assert enable(c)['status'] == 200
    pending = []
    notify = c.speech_servers.on_end
    c.speech_servers.on_end = lambda *args: pending.append(args)
    if ending == 'stop':
        c.stopSpeechServer({'profile': 'japanese'})
        assert not c.getVoiceStatus()['result']['tts_enabled']
    made[0].fail()  # Cleanup/natural exit reaches the hub before delivery.
    assert len(pending) == 1
    configure(c, 'external')
    assert enable(c)['status'] == 200
    generation = c.voice_events.generation()
    with utterance(c) as (token, sink):
        notify(*pending[0])
        notify(*pending[0])  # Even duplicate delivery is harmless.
        state = c.getVoiceStatus()['result']
        assert state['tts_enabled'] and state['active']
        assert state['tts_generation'] == generation
        assert not token.is_set()
    assert sink.data and c.voice_events.status()['completed'] == 1


def test_manual_unused_server_stop_then_external_on_survives_late_cleanup(lifecycle):
    c, _, made = lifecycle
    configure(c, 'external')
    run_server(c, 'japanese')
    c.stopSpeechServer({'profile': 'japanese'})
    assert enable(c)['status'] == 200
    generation = c.voice_events.generation()
    with utterance(c) as (token, sink):
        made[0].fail()
        assert c.voice_events.generation() == generation
        assert c.getVoiceStatus()['result']['tts_enabled']
        assert not token.is_set()
    assert sink.data


def test_delayed_natural_end_cannot_disable_replacement_run_of_same_profile(lifecycle):
    c, _, made = lifecycle
    configure(c)
    run_server(c, 'japanese')
    assert enable(c)['status'] == 200
    pending, notify = [], c.speech_servers.on_end
    c.speech_servers.on_end = lambda *args: pending.append(args)
    made[0].fail()
    run_server(c, 'japanese')
    assert enable(c)['status'] == 200
    generation = c.voice_events.generation()
    with utterance(c) as (token, sink):
        notify(*pending[0])
        assert not token.is_set()
        assert c.getVoiceStatus()['result']['tts_enabled']
        assert c.voice_events.generation() == generation
    assert sink.data


@pytest.mark.parametrize('ending', ['stop', 'natural'])
def test_current_dependency_disables_and_publishes_one_tts_state_change(lifecycle, monkeypatch, ending):
    c, _, made = lifecycle
    configure(c)
    run_server(c, 'japanese')
    assert enable(c)['status'] == 200
    c.direct_voice.stop.reset_mock()
    generation = c.voice_events.generation()
    disable = MagicMock(wraps=c.voice_events.set_enabled)
    monkeypatch.setattr(c.voice_events, 'set_enabled', disable)
    with utterance(c) as (token, _):
        assert c.voice_events.publish(event('queued'))
        if ending == 'stop':
            c.stopSpeechServer({'profile': 'japanese'})
        made[0].fail()
        made[0].on_end('japanese')
        assert token.is_set()
        state = c.getVoiceStatus()['result']  # Existing UI notification: polled state.
        assert not state['tts_enabled'] and state['queued'] == 0
        assert state['tts_generation'] == generation + 1
        assert disable.call_args_list == [call(False, expected_generation=generation)]
    c.direct_voice.stop.assert_not_called()


def test_current_dependency_end_releases_other_toggle_owned_server(lifecycle):
    c, m, made = lifecycle
    m.config.ENABLE_TRANSLATION = True
    assert c.setVoiceSettings(dict(mode='original', mic_mode='translated', direct_policy='mix',
        target_slot='1', output_device='cable', japanese_server='bundled',
        multilingual_server='bundled'))['status'] == 200
    run_server(c, 'multilingual')  # Settings owns English; ON owns Japanese.
    assert enable(c)['status'] == 200
    assert c._tts_owned == {'japanese': 1}
    generation = c.voice_events.generation()
    made[0].fail()
    assert not c.getVoiceStatus()['result']['tts_enabled']
    assert made[1].health()['state'] == 'stopping'
    made[1].fail()
    assert c.voice_events.generation() == generation + 1


def test_toggle_owned_off_keeps_external_on_alive_after_child_cleanup(lifecycle):
    c, _, made = lifecycle
    configure(c)
    assert enable(c)['status'] == 200  # ON starts and owns the fake child.
    assert c._tts_owned == {'japanese': 1}
    c.disableTts()
    assert made[0].health()['state'] == 'stopping'
    configure(c, 'external')
    assert enable(c)['status'] == 200
    generation = c.voice_events.generation()
    with utterance(c) as (token, _):
        made[0].fail()
        assert not token.is_set()
        assert c.voice_events.generation() == generation
        assert c.getVoiceStatus()['result']['tts_enabled']
    assert not c._tts_released


@pytest.mark.parametrize('change', ['stop', 'mute', 'save'])
def test_current_dependency_crash_after_other_epoch_changes_still_disables(lifecycle, change):
    c, _, made = lifecycle
    configure(c)
    run_server(c, 'japanese')
    assert enable(c)['status'] == 200
    if change == 'stop':
        c.stopVoice()
    elif change == 'mute':
        c.voice_events.set_muted(True)
    else:
        configure(c)
    generation = c.voice_events.generation()
    made[0].fail()
    assert not c.getVoiceStatus()['result']['tts_enabled']
    assert c.voice_events.generation() == generation + 1


def test_stop_during_health_check_cannot_enable_a_dead_dependency(lifecycle, monkeypatch):
    c, m, made = lifecycle
    configure(c)
    run_server(c, 'japanese')
    monkeypatch.setattr(m.SpeechCppTTS, 'check_health',
                        lambda self: c.stopSpeechServer({'profile': 'japanese'}))
    assert enable(c) == {'status': 409, 'result': {'error_code': 'speech_server_not_ready'}}
    assert not c.getVoiceStatus()['result']['tts_enabled']
    made[0].fail()
    assert not c.getVoiceStatus()['result']['tts_enabled']


def test_saved_endpoint_change_while_enabled_updates_server_dependency(lifecycle):
    c, _, made = lifecycle
    configure(c, 'external')
    run_server(c, 'japanese')
    assert enable(c)['status'] == 200
    configure(c)  # Saving retains ON, but now it uses the bundled run.
    made[0].fail()
    assert not c.getVoiceStatus()['result']['tts_enabled']


def test_settings_change_between_dependency_check_and_disable_is_not_cancelled(lifecycle, monkeypatch):
    c, _, made = lifecycle
    configure(c)
    run_server(c, 'japanese')
    assert enable(c)['status'] == 200
    original = c.voice_events.set_enabled
    changed = []

    def raced(enabled, expected_generation=None):
        if not enabled and not changed:
            configure(c, 'external')
            changed.append(c.voice_events.generation())
        return original(enabled, expected_generation=expected_generation)

    monkeypatch.setattr(c.voice_events, 'set_enabled', raced)
    made[0].fail()
    assert c.getVoiceStatus()['result']['tts_enabled']
    assert c.voice_events.generation() == changed[0]
