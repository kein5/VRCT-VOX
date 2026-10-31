"""Language detection: what speech.cpp advertises and reports, without a model.

The option and event shapes are copied from speech.cpp 0.10.0's own
/v1/models and Realtime responses for Qwen3-ASR-0.6B and Haas-ja v1.0.
"""
import importlib
import json

import pytest

from models.audio_routing.source_bridge import Endpoint
from test_realtime_session import Dependencies
from test_realtime_delivery import eventually

QWEN_LANGUAGE = {'name': 'language', 'type': 'string', 'required': False, 'steers': True,
                 'default': 'auto', 'choices': ['de', 'en', 'ja', 'zh']}
HAAS_LANGUAGE = {'name': 'language', 'type': 'string', 'required': False, 'steers': False,
                 'default': 'auto', 'choices': ['ja']}


@pytest.mark.parametrize('options,detects', [
    ([QWEN_LANGUAGE, {'name': 'prompt', 'default': ''}], True),
    ([HAAS_LANGUAGE, {'name': 'keywords', 'default': ''}], False),  # One choice: nothing to detect.
    ([dict(QWEN_LANGUAGE, default='ja')], False),
    ([{'name': 'language'}], False),
    ([], False),
])
def test_detection_comes_from_the_language_option(options, detects):
    m = importlib.import_module('models.transcription.speechcpp_asr')
    assert m._detects(options) is detects


def test_recognizers_report_detection(monkeypatch):
    m = importlib.import_module('models.transcription.speechcpp_asr')
    payload = {'data': [
        {'id': 'Qwen3-ASR-0.6B', 'speech': {'task': 'recognition', 'languages': ['de', 'en', 'ja', 'zh'],
                                            'options': [QWEN_LANGUAGE]}},
        {'id': 'Haas-616M-ja-v1.0', 'speech': {'task': 'recognition', 'languages': ['ja'],
                                               'options': [HAAS_LANGUAGE]}},
        {'id': 'silero-vad', 'speech': {'task': 'detection', 'languages': [], 'options': []}}]}
    client = m.SpeechCppASR('http://127.0.0.1:8080')
    monkeypatch.setattr(client, '_request', lambda *args, **kwargs: (json.loads(json.dumps(payload)), None))
    assert [(row.id, row.detects_language) for row in client.recognizers()] == [
        ('Qwen3-ASR-0.6B', True), ('Haas-616M-ja-v1.0', False)]


def test_completed_events_carry_the_detected_language_only_on_finals():
    events = importlib.import_module('models.transcription.realtime_events')
    r = events.TranscriptEvents('speaker', 'session-a')
    prefix = 'conversation.item.input_audio_transcription.'
    r.accept({'type': 'input_audio_buffer.speech_started', 'event_id': 'e1', 'item_id': 'a'})
    partial = r.accept({'type': prefix + 'delta', 'event_id': 'e2', 'item_id': 'a', 'delta': 'Guten'})[0]
    final = r.accept({'type': prefix + 'completed', 'event_id': 'e3', 'item_id': 'a', 'stop': 'complete',
                      'transcript': 'Guten Abend.', 'languages': [{'code': 'de'}]})[0]
    assert (partial.language, final.language, final.text) == ('', 'de', 'Guten Abend.')
    for i, languages in enumerate(([], [{'code': 'DE; drop'}], 'de', [{'code': 3}], None)):
        item = f'b{i}'
        r.accept({'type': 'input_audio_buffer.speech_started', 'event_id': item + 's', 'item_id': item})
        row = {'type': prefix + 'completed', 'event_id': item + 'c', 'item_id': item,
               'stop': 'complete', 'transcript': 'x'}
        if languages is not None:
            row['languages'] = languages
        assert r.accept(row)[0].language == ''


def make_session(monkeypatch, language, models):
    m = importlib.import_module('models.transcription.realtime_session')
    settings = importlib.import_module('models.transcription.realtime_settings')
    deps = Dependencies()
    deps.models = models
    monkeypatch.setattr(m, 'SpeechCppASR', deps.rest)
    return m.RealtimeSession('speaker', settings.SessionOptions('http://127.0.0.1:8080', 'asr', language),
                             Endpoint(1, 2, 'selected', 'Audio/Sink'),
                             capture_factory=deps.capture, client_factory=deps.client), deps


@pytest.mark.parametrize('detects,state,code', [
    (True, 'ready', None),
    (False, 'failed', 'realtime_language_auto_unsupported'),
])
def test_session_preflight_accepts_auto_only_for_a_detecting_model(monkeypatch, detects, state, code):
    from models.transcription.speechcpp_asr import RecognitionModel
    s, deps = make_session(monkeypatch, 'auto', (RecognitionModel('asr', ('ja', 'en'), True, detects),))
    try:
        s.start()
        eventually(lambda: s.health()['state'] == state)
        assert s.health()['error_code'] == code
        assert bool(deps.clients) is detects  # A refused language never opens the stream.
    finally:
        s.close()
