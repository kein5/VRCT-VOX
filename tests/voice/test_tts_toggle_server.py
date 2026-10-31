"""The main TTS toggle owns only the bundled server it started; fake processes only."""
# ruff: noqa: F811 -- pytest uses imported fixtures by name.
from dataclasses import replace
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock

import pytest
import yaml

from models.speech_server import runtime
from test_controller_integration import controller_module  # noqa: F401
from test_realtime_controls import app  # noqa: F401
from test_scheduler import until
from test_speech_server_controls import OwnedProcess, owned, run_server  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


class LoadingProcess(OwnedProcess):
    """Stays preparing until the test publishes readiness, like a model load."""

    def start(self):
        self.value.update(state='preparing')

    def ready(self):
        self.value.update(state='ready', base_url='http://127.0.0.1:32123')

    def fail(self, code='speech_server_exited'):
        self.value.update(state='failed', base_url=None, error_code=code)
        self.on_end(self.profile)


@pytest.fixture
def toggle(app, owned, monkeypatch):
    c, m, _ = app
    settings, made = owned
    monkeypatch.setattr(runtime, 'SpeechServer', LoadingProcess)
    # A fake that is never made ready must fail the test, not hang it.
    monkeypatch.setattr(m.Controller, '_TTS_SERVER_WAIT', 3)
    assert c.setSpeechServerSettings(settings)['status'] == 200
    assert c.setVoiceSettings(dict(mode='original', output_device='cable', japanese_server='bundled'))['status'] == 200
    c.voice_events.set_muted(False)
    checked = []
    monkeypatch.setattr(m.SpeechCppTTS, 'check_health', lambda self: checked.append(self.base_url))
    return c, m, made, checked


def server(c, role='japanese'):
    return c.getSpeechServerState()['result'][role]


def enable(c):
    return c.enableTts({'generation': c.voice_events.generation()})


def enable_in_background(c):
    """Run ON like a mainloop worker; returns (thread, result list)."""
    generation, result = c.voice_events.generation(), []
    worker = Thread(target=lambda: result.append(c.enableTts({'generation': generation})))
    worker.start()
    return worker, result


def finish(worker, result):
    worker.join(2)
    assert not worker.is_alive()
    return result[0]


def test_on_starts_server_waits_for_model_and_off_stops_only_that_server(toggle):
    c, _, made, checked = toggle
    assert c.getVoiceStatus()['result']['tts_server_starting'] is False
    assert c.startSpeechServer(dict(profile='asr', generation=0))['status'] == 200
    made[0].ready()
    worker, result = enable_in_background(c)
    until(lambda: c.getVoiceStatus()['result']['tts_server_starting'])
    assert [p.profile for p in made] == ['asr', 'japanese']
    assert server(c)['state'] == 'preparing'
    assert not c.voice_events.status()['tts_enabled'] and not checked
    made[1].ready()
    response = finish(worker, result)
    assert response['status'] == 200, response
    assert response['result']['tts_enabled'] and not response['result']['tts_server_starting']
    assert checked == ['http://127.0.0.1:32123']
    assert c.disableTts()['status'] == 200
    assert server(c)['state'] == 'stopping'
    assert server(c, 'asr')['state'] == 'ready'  # The separate ASR server is never touched.


@pytest.mark.parametrize('phase', ['ready', 'preparing'])
def test_off_leaves_a_server_started_from_settings_running(toggle, phase):
    c, _, made, _ = toggle
    run_server(c, 'japanese')
    if phase == 'ready':
        made[0].ready()
        assert enable(c)['status'] == 200
    else:
        # Still loading from Settings: ON waits for it but does not adopt it.
        worker, result = enable_in_background(c)
        until(lambda: c.getVoiceStatus()['result']['tts_server_starting'])
        made[0].ready()
        assert finish(worker, result)['status'] == 200
    assert len(made) == 1
    c.disableTts()
    assert server(c)['state'] == 'ready'


def test_off_while_starting_cancels_quietly_and_stops_the_server(toggle):
    c, _, made, checked = toggle
    worker, result = enable_in_background(c)
    until(lambda: c.getVoiceStatus()['result']['tts_server_starting'])
    assert c.disableTts()['status'] == 200
    response = finish(worker, result)
    assert response == {'status': 409, 'result': {'error_code': 'tts_enable_cancelled'}}
    assert made[0].health()['state'] == 'stopping' and not checked
    status = c.getVoiceStatus()['result']
    assert not status['tts_enabled'] and not status['tts_server_starting']


@pytest.mark.parametrize('failure,code', [('speech_server_out_of_memory', 'speech_server_out_of_memory'),
                                          ('speech_server_exited', 'speech_server_start_failed')])
def test_start_failure_leaves_tts_off_and_names_the_reason(toggle, failure, code):
    c, _, made, checked = toggle
    worker, result = enable_in_background(c)
    until(lambda: c.getVoiceStatus()['result']['tts_server_starting'])
    made[0].fail(failure)
    assert finish(worker, result) == {'status': 409, 'result': {'error_code': code}}
    assert not c.voice_events.status()['tts_enabled'] and not checked
    assert server(c)['error_code'] == failure


def test_route_and_output_blockers_are_named_before_any_model_load(toggle):
    c, _, made, _ = toggle
    c.voice_events.set_muted(True)
    assert enable(c)['result']['error_code'] == 'voice_route_muted'
    c.voice_events.set_muted(False)
    # Saving forbids this; a restored or raced configuration can still lack it.
    c.voice_events.configure(replace(c.voice_events.settings, output_device=''))
    assert enable(c)['result']['error_code'] == 'tts_output_missing'
    assert not made


def test_missing_model_is_named_and_starts_nothing(toggle):
    c, _, made, _ = toggle
    settings = c.getSpeechServerSettings()['result']
    settings['profiles']['japanese']['model'] = ''
    c.setSpeechServerSettings(settings)
    assert enable(c)['result']['error_code'] == 'speech_server_model_invalid'
    assert not made and server(c)['state'] == 'stopped'


def test_external_server_keeps_the_existing_check(toggle, monkeypatch):
    c, m, made, _ = toggle
    c.setVoiceSettings(dict(mode='original', output_device='cable', japanese_server='external'))

    def unhealthy(self):
        raise m.SpeechError('speech_server_not_ready')

    monkeypatch.setattr(m.SpeechCppTTS, 'check_health', unhealthy)
    assert enable(c)['result']['error_code'] == 'speech_server_not_ready'
    assert not made


def test_settings_stop_and_restart_ends_toggle_ownership(toggle):
    c, _, made, _ = toggle
    worker, result = enable_in_background(c)
    until(lambda: made)
    made[0].ready()
    assert finish(worker, result)['status'] == 200
    # Stopping from Settings turns TTS off; the user's new run is theirs.
    c.stopSpeechServer(dict(profile='japanese'))
    assert not c.voice_events.status()['tts_enabled']
    run_server(c, 'japanese')
    made[1].ready()
    assert enable(c)['status'] == 200
    c.disableTts()
    assert server(c)['state'] == 'ready' and len(made) == 2


def test_tts_ending_elsewhere_releases_the_toggle_server(toggle):
    c, _, made, _ = toggle
    worker, result = enable_in_background(c)
    until(lambda: made)
    made[0].ready()
    assert finish(worker, result)['status'] == 200
    # The other TTS server (started from Settings) ends: TTS is off, so the
    # toggle's server is not left running with nobody to turn it off.
    run_server(c, 'multilingual')
    c.stopSpeechServer(dict(profile='multilingual'))
    assert not c.voice_events.status()['tts_enabled']
    assert server(c)['state'] == 'stopping'


def test_end_of_the_run_off_stopped_keeps_a_quick_on_valid(toggle):
    c, _, made, _ = toggle
    worker, result = enable_in_background(c)
    until(lambda: made)
    made[0].ready()
    assert finish(worker, result)['status'] == 200
    generation = c.disableTts()['result']['tts_generation']
    made[0].value.update(state='stopped')
    made[0].on_end('japanese')  # The child exits after OFF and its end is published.
    assert c.voice_events.generation() == generation
    result = []
    worker = Thread(target=lambda: result.append(c.enableTts({'generation': generation})))
    worker.start()
    until(lambda: len(made) == 2)
    made[1].ready()
    assert finish(worker, result)['status'] == 200


def test_shutdown_while_starting_stops_the_server_and_fails_the_toggle(toggle):
    c, m, made, _ = toggle
    worker, result = enable_in_background(c)
    until(lambda: c.getVoiceStatus()['result']['tts_server_starting'])
    m.config.saveConfigToFile = MagicMock()
    assert c.shutdown()['status'] == 200
    assert finish(worker, result)['status'] == 409
    assert made[0].health()['state'] == 'stopped'
    assert not c.voice_events.status()['tts_enabled']


def test_stop_with_a_generation_never_stops_a_newer_run(owned):
    made = owned[1]
    hub = runtime.SpeechServers()
    hub.start('japanese', owned[0]['profiles']['japanese'], 0)
    assert hub.stop('japanese', generation=0) is False
    assert made[0].health()['state'] == 'ready'
    assert hub.stop('japanese', generation=1) is True
    assert made[0].health()['state'] == 'stopping'


def test_every_code_on_can_report_has_an_english_and_japanese_next_step(controller_module):
    codes = {'tts_state_changed', 'voice_route_closed', 'voice_route_muted', 'tts_source_not_selected',
             'tts_translation_not_ready', 'tts_language_unsupported', 'tts_output_missing',
             'speech_server_not_ready', 'speech_server_or_settings_not_ready', 'speech_server_model_invalid',
             'speech_server_start_failed', 'speech_server_busy', *controller_module.Controller._TTS_START_FAILURES}
    for language in ('en', 'ja'):
        text = yaml.safe_load((ROOT / 'locales' / f'{language}.yml').read_text(encoding='utf-8'))['voice_ui']
        assert codes <= set(text['errors']), (language, codes - set(text['errors']))
        assert text['tts_server_starting']
