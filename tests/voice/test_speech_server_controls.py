"""Controller and receiver contracts; fake only owned processes and OS capture."""
# ruff: noqa: F811 -- pytest uses imported fixtures by name.
from dataclasses import replace
from queue import Queue
from threading import Event
from time import monotonic
from unittest.mock import MagicMock

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.speech_server import runtime
from models.speech_server.settings import normalize_settings
from models.tts.settings import VoiceSettings
from test_controller_integration import controller_module  # noqa: F401
from test_priority_cancel import mainloop_module, wire_message  # noqa: F401
from test_realtime_controls import app, start, request  # noqa: F401
from test_scheduler import Sink, event, until


class OwnedProcess:
    instances = None

    def __init__(self, profile, options, *, on_end):
        self.profile, self.options, self.on_end = profile, options, on_end
        self.value = dict(state='stopped', base_url=None, error_code=None)
        self.instances.append(self)

    def start(self):
        self.value.update(state='ready', base_url='http://127.0.0.1:32123')

    def stop(self):
        self.value.update(state='stopping', base_url=None)

    def close(self, timeout=3):
        self.value.update(state='stopped', base_url=None)
        return True

    def health(self):
        return dict(self.value)

    def fail(self):
        self.value.update(state='failed', base_url=None, error_code='speech_server_exited')
        self.on_end(self.profile)


@pytest.fixture
def owned(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(OwnedProcess, 'instances', made)
    monkeypatch.setattr(runtime, 'SpeechServer', OwnedProcess)
    model = tmp_path / 'model.gguf'
    model.write_bytes(b'GGUF' + b'\0' * 16)
    settings = normalize_settings({})
    for role, row in settings['profiles'].items():
        row['model'] = str(model)
        if role == 'asr':
            row['vad_model'] = str(model)
    return settings, made


def run_server(c, role):
    result = c.startSpeechServer(dict(profile=role, generation=c.getSpeechServerState()['result'][role]['generation']))
    assert result['status'] == 200, result


def test_restore_and_save_never_start_and_invalid_settings_do_not_mutate(app, owned):
    c, m, _ = app
    settings, made = owned
    assert c.getSpeechServerSettings()['result'] == normalize_settings({})
    assert c.setSpeechServerSettings(settings)['status'] == 200
    assert m.config.SPEECH_SERVER_SETTINGS == settings
    assert c.setSpeechServerSettings({**settings, 'running': True})['status'] == 400
    assert c.getSpeechServerSettings()['result'] == settings
    other = m.Controller()
    try:
        assert other.getSpeechServerSettings()['result'] == settings
        assert all(s['state'] == 'stopped' for s in other.getSpeechServerState()['result'].values())
        assert not made
    finally:
        other.speech_servers.close()
        other._closeRealtimeASR()
        other.direct_voice.close()
        other.voice_route.close()
        other.voice_events.close()


@pytest.mark.parametrize('payload', [None, {}, {'profile': 'bad'}, {'profile': []}, {'profile': 'asr', 'generation': True}, {'profile': 'asr', 'generation': -1}, {'profile': 'asr', 'generation': 0, 'command': 'bad'}])
def test_invalid_start_is_safe_and_never_launches(app, owned, payload):
    c, _, _ = app
    assert c.startSpeechServer(payload)['status'] == 400
    assert not owned[1]


def test_stop_invalidates_generation_and_start_validates_files(app, owned):
    c, _, _ = app
    assert c.startSpeechServer(dict(profile='asr', generation=0))['status'] == 400
    c.setSpeechServerSettings(owned[0])
    run_server(c, 'asr')
    assert c.startSpeechServer(dict(profile='asr', generation=1))['status'] == 409
    before = monotonic()
    assert c.stopSpeechServer(dict(profile='asr'))['status'] == 200
    assert monotonic() - before < .1
    assert c.startSpeechServer(dict(profile='asr', generation=0))['status'] == 409
    assert len(owned[1]) == 1
    assert c.stopSpeechServer(dict(profile='asr', pid=123))['status'] == 400


@pytest.mark.parametrize('field', ['japanese_server', 'multilingual_server'])
def test_voice_endpoint_selection_is_explicit(field):
    assert VoiceSettings.from_dict({}).to_dict()[field] == 'external'
    with pytest.raises(ValueError):
        VoiceSettings.from_dict({field: 'automatic'})


@pytest.mark.parametrize('mode,language,role', [('original', 'Japanese', 'japanese'), ('original', 'English', 'multilingual'), ('translated', 'English', 'multilingual')])
def test_tts_resolves_selected_language_role_without_requiring_external_url(mode, language, role):
    settings = VoiceSettings.from_dict(dict(mode=mode, output_device='cable', japanese_server='bundled', multilingual_server='bundled'))
    message = replace(event(), source_language=language, target_language=language, translated_text='translated')
    resolve = MagicMock(return_value='http://127.0.0.1:32123')
    result = settings.request_for(message, resolve_server=resolve)
    resolve.assert_called_once_with(role)
    assert result[0] == 'http://127.0.0.1:32123'
    with pytest.raises((ValueError, RuntimeError)):
        settings.request_for(message)


def test_bundled_not_ready_never_calls_external_http_and_preserves_chat(app, pcm_server):
    c, m, _ = app
    with pcm_server() as (url, requests):
        assert c.setVoiceSettings(dict(mode='original', output_device='cable', japanese_url=url, japanese_server='bundled'))['status'] == 200
        c.voice_events.router = AudioRouter(lambda *args: Sink())
        assert c.chatMessage(dict(id='missing', message='hello'))['status'] == 200
        until(lambda: c.voice_events.status()['errors'] == 1)
        assert requests == []
        m.model.oscSendMessage.assert_called_once()


@pytest.mark.parametrize('ending', ['stop', 'fault'])
def test_owned_tts_ending_cancels_active_and_queued_audio_only(app, owned, ending):
    c, _, _ = app
    c.setSpeechServerSettings(owned[0])
    run_server(c, 'japanese')
    assert c.setVoiceSettings(dict(mode='original', output_device='cable', japanese_server='bundled'))['status'] == 200
    started = Event()

    class Provider:
        def __init__(self, url):
            assert url == 'http://127.0.0.1:32123'

        def synthesize_stream(self, text, voice, language, token):
            started.set()
            token.wait(2)
            token.check()
            yield

    c.voice_events.provider_factory = Provider
    c.direct_voice.stop = MagicMock()
    start(c)
    c.voice_events.publish(event('active'))
    assert started.wait(1)
    c.voice_events.publish(event('queued'))
    if ending == 'stop':
        c.stopSpeechServer(dict(profile='japanese'))
    else:
        owned[1][0].fail()
    until(lambda: c.voice_events.status()['cancelled'] == 1)
    assert c.voice_events.status()['queued'] == 0
    assert c.getRealtimeASRState()['result']['mic']['requested']
    c.direct_voice.stop.assert_not_called()


def test_bundled_asr_selection_models_start_and_no_external_fallback(app, owned, monkeypatch):
    c, m, made = app
    settings = c.getRealtimeASRSettings()['result']
    settings['server'] = 'bundled'
    assert c.setRealtimeASRSettings(settings)['status'] == 200
    adapter = MagicMock()
    adapter.return_value.recognizers.return_value = []
    monkeypatch.setattr(m, 'SpeechCppASR', adapter)
    assert c.getRealtimeASRModels()['result']['error_code'] == 'speech_server_not_ready'
    adapter.assert_not_called()
    assert c.startRealtimeASR(request(c))['status'] == 409
    assert not made
    c.setSpeechServerSettings(owned[0])
    run_server(c, 'asr')
    result = c.getRealtimeASRModels()['result']
    assert result == dict(server='bundled', configured_url=settings['base_url'], base_url='http://127.0.0.1:32123', models=[], error_code=None)
    start(c)
    assert made[0].options.base_url == result['base_url']
    assert c.getRealtimeASRSettings()['result'] == settings
    settings['server'] = 'external'
    assert c.setRealtimeASRSettings(settings)['status'] == 200
    assert not made[0].active
    start(c)
    assert made[1].options.base_url == settings['base_url']


@pytest.mark.parametrize('ending', ['stop', 'fault'])
def test_asr_server_ending_invalidates_late_delivery_but_keeps_direct_voice(app, owned, ending):
    c, m, made = app
    c.setSpeechServerSettings(owned[0])
    run_server(c, 'asr')
    assert c.setRealtimeASRSettings({**c.getRealtimeASRSettings()['result'], 'server': 'bundled'})['status'] == 200
    entered, release = Event(), Event()

    def translate(*args, **kwargs):
        entered.set()
        release.wait(2)
        return ['translation'], [True]

    m.config.ENABLE_TRANSLATION = True
    m.model.getInputTranslate.side_effect = translate
    c.direct_voice.stop = MagicMock()
    start(c)
    start(c, 'speaker')
    made[0].emit(final=True)
    try:
        assert entered.wait(1)
        if ending == 'stop':
            c.stopSpeechServer(dict(profile='asr'))
        else:
            owned[1][0].fail()
        assert all(not s.active for s in made)
        release.set()
        assert c._drainRealtimeASR('mic')
        m.model.oscSendMessage.assert_not_called()
        m.model.addTranslationHistory.assert_not_called()
        c.direct_voice.stop.assert_not_called()
    finally:
        release.set()


def test_unused_asr_stop_does_not_interrupt_external_capture(app):
    c, _, made = app
    start(c)
    c.stopSpeechServer(dict(profile='asr'))
    assert made[0].active


def test_application_shutdown_closes_owned_servers_and_rejects_new_start(app, owned):
    c, m, _ = app
    c.setSpeechServerSettings(owned[0])
    run_server(c, 'japanese')
    m.config.saveConfigToFile = MagicMock()
    assert c.shutdown()['status'] == 200
    assert owned[1][0].health()['state'] == 'stopped'
    assert c.startSpeechServer(dict(profile='japanese', generation=c.getSpeechServerState()['result']['japanese']['generation']))['status'] == 409


def test_stop_bypasses_blocked_handlers_and_rejects_queued_start(mainloop_module, owned, monkeypatch):
    m, c = mainloop_module, mainloop_module.controller
    c.setSpeechServerSettings(owned[0])
    entered = [Event() for _ in range(3)]
    release, stopped, drained = Event(), Event(), Event()
    pending, results = Queue(), []

    def busy(index):
        def handler(data):
            entered[index].set()
            release.wait(3)
            return dict(status=200, result=None)
        return handler

    def start_handler(data):
        results.append(c.startSpeechServer(data))
        drained.set()
        return results[-1]

    def stop_handler(data):
        result = c.stopSpeechServer(data)
        stopped.set()
        return result

    mapping = {f'/busy/{i}': dict(status=True, variable=busy(i)) for i in range(3)}
    mapping.update({'/run/start_speech_server': dict(status=True, variable=start_handler), '/run/stop_speech_server': dict(status=True, variable=stop_handler)})
    main = m.Main(c, mapping)
    monkeypatch.setattr(m.sys, 'stdin', type('Input', (), {'readline': lambda self: pending.get()})())
    main.startHandler()
    main.startReceiver()
    try:
        for i in range(3):
            pending.put(wire_message(f'/busy/{i}'))
        assert all(e.wait(1) for e in entered)
        pending.put(wire_message('/run/start_speech_server', dict(profile='japanese', generation=0)))
        pending.put(wire_message('/run/stop_speech_server', dict(profile='japanese')))
        assert stopped.wait(.25)
        release.set()
        assert drained.wait(1)
        assert results[0]['status'] == 409 and not owned[1]
    finally:
        main._stop_event.set()
        release.set()
        pending.put('')
        for thread in main._threads:
            thread.join(2)
