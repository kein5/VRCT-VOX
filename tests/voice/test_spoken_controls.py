"""Real Controller/delivery/HTTP PCM; injected ASR input and translation only."""
# ruff: noqa: F811 -- pytest injects the imported app fixture by name.
from threading import Event
from unittest.mock import MagicMock

import pytest

from models.audio_routing.audio_router import AudioRouter
from test_controller_integration import controller_module  # noqa: F401
from test_realtime_controls import app, captions, start  # noqa: F401
from test_realtime_delivery import eventually
from test_scheduler import Sink, until


def configure(c, m, url, **overrides):
    m.config.ENABLE_TRANSLATION = True
    m.model.getInputTranslate.return_value = (["Hello", "こんにちは"], [True, True])
    m.model.getOutputTranslate.return_value = (["Hello"], [True])
    c.changeToCTranslate2Process = MagicMock()
    settings = dict(mic_mode="translated", direct_policy="mix", output_device="cable",
                    multilingual_url=url)
    settings.update(overrides)
    assert c.setVoiceSettings(settings)['status'] == 200
    sink = Sink()
    c.voice_events.router = AudioRouter(lambda *args: sink)
    return sink


def test_final_mic_speaks_enabled_target_order_once_with_chat_off(app, pcm_server):
    c, m, made = app
    with pcm_server() as (url, requests):
        sink = configure(c, m, url, target_slot="2")
        m.config.SELECTED_TARGET_LANGUAGES['1'] = {
            '3': {'language': 'French', 'enable': False},
            '2': {'language': 'English', 'enable': True},
            '1': {'language': 'Japanese', 'enable': True},
        }
        start(c)
        made[0].emit(final=True)
        made[0].emit(final=True, revision=2)
        until(lambda: c.voice_events.status()['completed'] == 1)
        assert [body for _, body in requests] == [
            {'input': 'Hello', 'voice': 'ryan', 'language': 'en', 'response_format': 'pcm'}]
        assert b''.join(sink.data) == b'\x01\x00\x02\x00'
        assert m.model.oscSendMessage.call_count == 1
        assert m.model.addTranslationHistory.call_count == 1
        assert c.voice_events.status()['mode'] == 'off'


@pytest.mark.parametrize('excluded', ['partial', 'speaker', 'off', 'failed', 'disabled-target', 'translation-off'])
def test_ineligible_transcript_never_becomes_audio(app, pcm_server, excluded):
    c, m, made = app
    with pcm_server() as (url, requests):
        sink = configure(c, m, url, mic_mode='off' if excluded == 'off' else 'translated')
        if excluded == 'failed':
            m.model.getInputTranslate.return_value = (['text', 'こんにちは'], [False, True])
        if excluded == 'disabled-target':
            m.config.SELECTED_TARGET_LANGUAGES['1']['1']['enable'] = False
            m.model.getInputTranslate.return_value = (['こんにちは'], [True])
        if excluded == 'translation-off':
            m.config.ENABLE_TRANSLATION = False
        start(c, 'speaker' if excluded == 'speaker' else 'mic')
        made[0].emit(final=excluded != 'partial')
        eventually(lambda: any(p['state'] == ('partial' if excluded == 'partial' else 'translated')
                               for p in captions(c)))
        assert c.voice_events.status()['accepted'] == 0
        assert requests == [] and sink.data == []


@pytest.mark.parametrize('invalidate', ['stop', 'settings', 'target', 'translation-off'])
def test_blocked_translation_cannot_resurrect_mic_speech(app, pcm_server, invalidate):
    c, m, made = app
    entered, release, returned = Event(), Event(), Event()
    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        returned.set()
        return ['Hello', 'こんにちは'], [True, True]
    with pcm_server() as (url, requests):
        configure(c, m, url)
        m.model.getInputTranslate.side_effect = translate
        start(c)
        made[0].emit(final=True)
        try:
            assert entered.wait(1)
            if invalidate == 'stop':
                c.stopRealtimeASR({'source': 'mic'})
            elif invalidate == 'settings':
                assert c.setVoiceSettings(c.getVoiceSettings()['result'])['status'] == 200
            elif invalidate == 'target':
                m.config.SELECTED_TARGET_LANGUAGES['1']['1']['language'] = 'French'
            else:
                m.config.ENABLE_TRANSLATION = False
            release.set()
            assert returned.wait(1)
            if invalidate != 'stop':
                eventually(lambda: any(p['state'] == 'translated' for p in captions(c)))
            else:
                assert c._drainRealtimeASR('mic')
            assert c.voice_events.status()['accepted'] == 0 and requests == []
        finally:
            release.set()


@pytest.mark.parametrize('stop', ['explicit', 'session-failure'])
def test_mic_stop_interrupts_active_tts_and_chat_remains_available(app, pcm_server, stop):
    c, m, made = app
    entered, release = Event(), Event()
    def first_request(index):
        if not entered.is_set():
            entered.set()
            release.wait(2)
    with pcm_server(before_chunk=first_request) as (url, requests):
        sink = configure(c, m, 'http://localhost:8081', mode='original', target_slot='2', japanese_url=url)
        start(c)
        made[0].emit(final=True)
        try:
            assert entered.wait(1)
            if stop == 'explicit':
                c.stopRealtimeASR({'source': 'mic'})
            else:
                made[0].request_stop()
            until(lambda: c.voice_events.status()['cancelled'] == 1)
            m.config.ENABLE_TRANSLATION = False
            assert c.chatMessage({'id': 'new-chat', 'message': 'チャット'})['status'] == 200
            until(lambda: c.voice_events.status()['completed'] == 1)
            assert [body['input'] for _, body in requests] == ['こんにちは', 'チャット']
            assert b''.join(sink.data) == b'\x01\x00\x02\x00'
        finally:
            release.set()


@pytest.mark.parametrize('change', ['target', 'tab', 'translation-off'])
def test_language_settings_change_interrupts_already_queued_mic_audio(app, pcm_server, change):
    c, m, made = app
    entered, release = Event(), Event()
    def stalled(index):
        entered.set()
        release.wait(2)
    with pcm_server(before_chunk=stalled) as (url, requests):
        configure(c, m, url)
        c.updateTranslationEngineAndEngineList = MagicMock()
        start(c)
        made[0].emit(final=True)
        try:
            assert entered.wait(1)
            if change == 'target':
                c.setSelectedTargetLanguages({'1': {'1': {'language': 'French', 'enable': True}}})
            elif change == 'tab':
                c.setSelectedTabNo('2')
            else:
                c.setDisableTranslation()
            until(lambda: c.voice_events.status()['cancelled'] == 1)
        finally:
            release.set()


def test_delayed_previous_session_cleanup_does_not_cancel_new_mic_audio(app, pcm_server):
    c, m, made = app
    entered, release = Event(), Event()
    def stalled(index):
        entered.set()
        release.wait(2)
    with pcm_server(before_chunk=stalled) as (url, requests):
        sink = configure(c, m, url)
        start(c)
        old_cleanup = c._realtime_owners['mic'][1]._on_stopped
        c.stopRealtimeASR({'source': 'mic'})
        assert c._drainRealtimeASR('mic')
        start(c)
        made[1].emit(final=True)
        try:
            assert entered.wait(1)
            old_cleanup()
            release.set()
            until(lambda: c.voice_events.status()['completed'] == 1)
            assert b''.join(sink.data) == b'\x01\x00\x02\x00'
            assert c.voice_events.status()['cancelled'] == 0
        finally:
            release.set()


def test_managed_setting_controls_direct_branch_without_starting_capture(app):
    from test_managed_route import Gate, ready
    c, m, made = app
    gate = Gate()
    c.voice_route.gate = gate
    assert c.setVoiceSettings({'mic_mode': 'translated', 'routing': 'managed'})['status'] == 200
    ready(c.voice_route)
    assert gate.muted and gate.direct_muted and not made
    c.voice_route.resume()
    ready(c.voice_route)
    assert not gate.muted and gate.direct_muted
    assert c.setVoiceSettings({'mic_mode': 'off', 'routing': 'managed'})['status'] == 200
    ready(c.voice_route)
    assert gate.muted and not gate.direct_muted and not made


def test_optional_mic_enqueue_error_preserves_caption_osc_and_history(app, pcm_server):
    c, m, made = app
    with pcm_server() as (url, requests):
        configure(c, m, url)
        c.voice_events.publish = MagicMock(side_effect=RuntimeError('private content'))
        start(c)
        made[0].emit(final=True)
        eventually(lambda: any(p['state'] == 'translated' for p in captions(c)))
        assert m.model.oscSendMessage.call_count == 1
        assert m.model.addTranslationHistory.call_count == 1
        assert requests == []
        assert c.getRealtimeASRState()['result']['mic']['error_code'] is None
