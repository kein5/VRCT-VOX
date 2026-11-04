"""Message admission and fanout regressions with memory-only services."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Event, Thread
from unittest.mock import Mock

import pytest

import controller as module
from model import Model
from models.message_pipeline import CHAT_MESSAGE_SPEC
from models.message_snapshot import MessageSnapshot
from models.tts.settings import VoiceSettings
from test_message_delivery_revocation import app, captions, start, wait_for_finals  # noqa: F401


@pytest.fixture
def subject(app, monkeypatch):  # noqa: F811 - imported pytest fixture
    app.c.changeToCTranslate2Process = Mock()
    app.c.voice_events.publish = Mock(return_value=True)
    app.m.convertMessageToTransliteration = Mock(side_effect=lambda text, **kw: [dict(orig=text, **kw)])
    app.m.getTranslationHistory = Mock(return_value=[])
    app.m.translator = Mock()
    app.m.translator.isLoadedCTranslate2Model.return_value = False
    app.m.getInputTranslate = Model.getInputTranslate.__get__(app.m)
    app.m.getOutputTranslate = Model.getOutputTranslate.__get__(app.m)
    for languages in (app.cfg.SELECTED_YOUR_LANGUAGES, app.cfg.SELECTED_TARGET_LANGUAGES):
        for slots in languages.values():
            for entry in slots.values():
                entry['country'] = 'Japan' if entry['language'] == 'Japanese' else 'United States'
    app.cfg.SELECTED_TRANSLATION_ENGINES = {'1': 'OpenAI_API'}
    app.cfg.CTRANSLATE2_WEIGHT_TYPE = 'admitted-weight'
    app.logged_errors = Mock()
    monkeypatch.setattr(module, 'errorLogging', app.logged_errors)
    monkeypatch.setattr('model.errorLogging', app.logged_errors)
    app.process_logs = []
    monkeypatch.setattr(module, 'printLog', lambda line, *args: app.process_logs.append(line))
    with ThreadPoolExecutor(max_workers=3) as pool:
        app.m._translation_executor = pool
        yield app


def notices(subject):
    return [call.args[2]['data'] for call in subject.c.run.call_args_list
            if call.args[1] == '/run/message_output_error']


def test_snapshot_is_deeply_immutable(subject):
    snap = MessageSnapshot.capture(subject.cfg, CHAT_MESSAGE_SPEC, None)
    with pytest.raises(FrozenInstanceError):
        snap.translation_enabled = False
    with pytest.raises(TypeError):
        snap.target_languages['1']['enable'] = False
    with pytest.raises(TypeError):
        snap.format_parts['message']['prefix'] = 'new'


@pytest.mark.parametrize('source', ['chat', 'mic', 'speaker', 'ocr'])
def test_content_changes_during_translation_keep_every_sink_consistent(subject, source):
    c, m, cfg = subject.c, subject.m, subject.cfg
    cfg.CONVERT_MESSAGE_TO_HIRAGANA = True
    cfg.SEND_ONLY_TRANSLATED_MESSAGES = True
    if source in ('speaker', 'ocr'):
        cfg.SELECTED_YOUR_LANGUAGES['1']['1']['language'] = 'Japanese'
        cfg.SELECTED_TARGET_LANGUAGES['1']['1']['language'] = 'English'
    before_your = copy.deepcopy(cfg.SELECTED_YOUR_LANGUAGES['1'])
    before_targets = copy.deepcopy(cfg.SELECTED_TARGET_LANGUAGES['1'])
    before_format = copy.deepcopy(cfg.SEND_MESSAGE_FORMAT_PARTS if source in ('chat', 'mic') else cfg.RECEIVED_MESSAGE_FORMAT_PARTS)

    def translate(**request):
        assert request['source_language'] == 'English'
        assert request['target_language'] == 'Japanese'
        assert request['translator_name'] == 'OpenAI_API'
        assert request['weight_type'] == 'admitted-weight'
        # Slot 2 used to be enabled between translation and transliteration.
        cfg.SELECTED_TARGET_LANGUAGES['1']['2'].update(enable=True, language='Japanese')
        cfg.SELECTED_TARGET_LANGUAGES['1']['1']['language'] = 'French'
        cfg.SELECTED_YOUR_LANGUAGES['1']['1']['language'] = 'German'
        cfg.ENABLE_TRANSLATION = False
        cfg.SEND_ONLY_TRANSLATED_MESSAGES = False
        cfg.CONVERT_MESSAGE_TO_HIRAGANA = False
        cfg.CONVERT_MESSAGE_TO_ROMAJI = True
        cfg.OVERLAY_SHOW_ONLY_TRANSLATED_MESSAGES = True
        cfg.SEND_MESSAGE_FORMAT_PARTS = cfg.RECEIVED_MESSAGE_FORMAT_PARTS = {
            **before_format, 'translation': {'prefix': 'CHANGED', 'suffix': '', 'separator': '!'}}
        cfg.SELECTED_TRANSLATION_ENGINES['1'] = 'CTranslate2'
        cfg.CTRANSLATE2_WEIGHT_TYPE = 'changed-weight'
        cfg.SELECTED_TAB_NO = '2'  # Would also crash the old metadata reads.
        return '日本語の訳'

    m.translator.translate.side_effect = translate
    if source == 'chat':
        response = c.chatMessage({'id': 'row', 'message': 'original'})
        assert response['status'] == 200
        payload = response['result']
        event = c.voice_events.publish.call_args.args[0]
        assert (event.source_language, event.target_language, event.translated_text) == ('English', 'Japanese', '日本語の訳')
    else:
        getattr(c, source + 'Message')({'text': 'original', 'language': 'English'})
        payload = [call.args[2] for call in c.run.call_args_list if call.args[0] == 200][-1]
    assert payload['translations'] == [{'message': '日本語の訳', 'transliteration': [dict(orig='日本語の訳', hiragana=True, romaji=False)]}]
    if source != 'ocr':
        m.oscSendMessage.assert_called_once_with(c.messageFormatter('SEND', ['日本語の訳'], '', before_format))
    ws = m.websocketSendMessage.call_args.args[0]
    assert ws['translation'] == ['日本語の訳']
    assert ws['src_languages'] == (before_your if source in ('chat', 'mic') else before_targets)
    assert ws['dst_languages'] == (before_targets if source in ('chat', 'mic') else before_your)
    json.dumps(ws)  # Frozen mappings must not escape onto the wire.
    overlay = m.createOverlayImageLargeLog.call_args.args
    assert overlay[1:4] == ('original', 'English', ['日本語の訳'])
    assert overlay[4] == ws['dst_languages']
    if source == 'speaker':
        assert m.createOverlayImageSmallLog.call_args.args[3] == before_your
    assert not notices(subject)


def test_translation_enabled_after_admission_does_not_add_translation(subject):
    subject.cfg.ENABLE_TRANSLATION = False
    subject.c.voice_events.configure(VoiceSettings(mode='original'))
    subject.c.voice_events.publish.side_effect = lambda *args, **kw: setattr(subject.cfg, 'ENABLE_TRANSLATION', True)
    result = subject.c.chatMessage({'id': 'off', 'message': 'original'})
    assert result['result']['translations'] == []
    subject.m.translator.translate.assert_not_called()
    subject.m.oscSendMessage.assert_called_once_with('original')
    assert subject.m.websocketSendMessage.call_args.args[0]['translation'] == []


def test_sparse_target_slots_use_compact_translation_indices(subject):
    cfg = subject.cfg
    cfg.SELECTED_TARGET_LANGUAGES['1']['1']['enable'] = False
    cfg.SELECTED_TARGET_LANGUAGES['1']['3'].update(enable=True, language='Japanese', country='Japan')
    cfg.CONVERT_MESSAGE_TO_HIRAGANA = True
    subject.c.voice_events.configure(VoiceSettings(mode='translated', target_slot='3'))
    subject.m.translator.translate.return_value = '訳'
    result = subject.c.chatMessage({'id': 'sparse', 'message': 'source'})
    assert len(result['result']['translations']) == 1
    assert result['result']['translations'][0]['transliteration'][0]['orig'] == '訳'
    assert subject.c.voice_events.publish.call_args.args[0].translated_text == '訳'


@pytest.mark.parametrize('primary,fallback,origin,spoken,failed', [
    (False, False, 'failed', False, True),
    (False, None, 'failed', False, True),
    (None, None, 'unsupported', False, False),
    ('translated', None, 'translated', True, False),
    (False, 'fallback translation', 'translated', True, False),
    ('original', None, 'translated', True, False),  # Text equality is not provenance.
])
def test_chat_speech_requires_a_real_translation(subject, primary, fallback, origin, spoken, failed):
    subject.m.translator.translate.side_effect = [primary, fallback]
    result = subject.c.chatMessage({'id': 'voice', 'message': 'original'})
    assert result['status'] == 200
    expected = primary if isinstance(primary, str) else fallback if isinstance(fallback, str) else 'original'
    assert result['result']['translations'][0]['message'] == expected
    assert subject.c.voice_events.publish.called is spoken
    assert subject.c.changeToCTranslate2Process.called is failed
    if spoken:
        assert subject.c.voice_events.publish.call_args.args[0].translated_text == expected
    # Exercise the explicit provenance contract, independently of text equality.
    subject.m.translator.translate.side_effect = [primary, fallback]
    assert subject.m.getTranslate('OpenAI_API', 'English', 'Japanese', 'Japan', 'original', with_provenance=True)[2] == origin


@pytest.mark.parametrize('output,method', [
    ('osc', 'oscSendMessage'), ('overlay_large', 'createOverlayImageLargeLog'),
    ('websocket', 'websocketSendMessage'), ('logger', 'logger'), ('history', 'addTranslationHistory'), ('tts', 'tts'),
])
def test_chat_sink_failure_returns_success_and_continues(subject, output, method):
    c, m = subject.c, subject.m
    m.translator.translate.return_value = 'translated'
    target = c.voice_events.publish if method == 'tts' else m.logger.info if method == 'logger' else getattr(m, method)
    target.side_effect = RuntimeError('synthetic sink failure')
    result = c.chatMessage({'id': 'partial', 'message': 'original'})
    assert result['status'] == 200
    assert result['result']['output_failures'] == [{'output': output, 'error_code': 'MESSAGE_OUTPUT_FAILED'}]
    assert notices(subject) == [{'id': 'partial', 'source': 'chat', 'output': output, 'error_code': 'MESSAGE_OUTPUT_FAILED'}]
    subject.logged_errors.assert_called_once()
    for sink in (m.oscSendMessage, m.createOverlayImageLargeLog, m.websocketSendMessage, m.logger.info,
                 m.addTranslationHistory, c.voice_events.publish):
        assert sink.call_count == 1  # Includes the failed attempt; no replay.


@pytest.mark.parametrize('source,output,method', [
    ('mic', 'osc', 'oscSendMessage'), ('mic', 'overlay_large', 'updateOverlayLargeLog'),
    ('speaker', 'overlay_small', 'createOverlayImageSmallLog'),
    ('speaker', 'overlay_small', 'updateOverlaySmallLog'),
    ('mic', 'clipboard', 'setCopyToClipboardAndPasteFromClipboard'),
    ('mic', 'websocket', 'checkWebSocketServerAlive'),
    ('speaker', 'logger', 'logger'), ('mic', 'ui', 'ui'),
])
def test_legacy_output_failure_never_becomes_an_asr_failure(subject, source, output, method):
    c, m = subject.c, subject.m
    m.translator.translate.return_value = 'translated'
    if method == 'ui':
        c.run.side_effect = lambda status, endpoint, payload: (_ for _ in ()).throw(RuntimeError('ui')) if endpoint == '/run/transcription_send_mic_message' else None
    else:
        target = m.logger.info if method == 'logger' else getattr(m, method)
        target.side_effect = RuntimeError('sink')
    getattr(c, source + 'Message')({'text': 'first', 'language': 'English'})
    getattr(c, source + 'Message')({'text': 'next', 'language': 'English'})
    assert len(notices(subject)) == 2
    assert all(record['output'] == output for record in notices(subject))
    assert subject.cfg.ENABLE_TRANSCRIPTION_SEND and subject.cfg.ENABLE_TRANSCRIPTION_RECEIVE
    assert not any('recognition_error' in call.args[1] or '/disable/' in call.args[1] for call in c.run.call_args_list)
    assert m.addTranslationHistory.call_count == 2
    if method != 'ui':
        assert len([call for call in c.run.call_args_list if call.args[0] == 200]) == 2
    if method not in ('logger', 'checkWebSocketServerAlive'):
        assert m.websocketSendMessage.call_count == 2
    assert m.logger.info.call_count == 2


def test_live_output_disables_after_translation_are_honored(subject):
    def translate(**kwargs):
        for flag in ('SEND_MESSAGE_TO_VRC', 'OVERLAY_LARGE_LOG', 'ENABLE_CLIPBOARD', 'LOGGER_FEATURE'):
            setattr(subject.cfg, flag, False)
        subject.m.checkWebSocketServerAlive.return_value = False
        return 'translated'
    subject.m.translator.translate.side_effect = translate
    subject.c.micMessage({'text': 'original', 'language': 'English'})
    for method in ('oscSendMessage', 'updateOverlayLargeLog', 'websocketSendMessage', 'setCopyToClipboardAndPasteFromClipboard'):
        getattr(subject.m, method).assert_not_called()
    subject.m.logger.info.assert_not_called()
    assert subject.c.run.call_args.args[0] == 200


def test_live_overlay_disable_during_render_skips_publication(subject):
    subject.m.translator.translate.return_value = 'translated'
    subject.m.createOverlayImageLargeLog.side_effect = lambda *args: setattr(subject.cfg, 'OVERLAY_LARGE_LOG', False)
    result = subject.c.chatMessage({'id': 'overlay', 'message': 'original'})
    assert result['status'] == 200
    subject.m.updateOverlayLargeLog.assert_not_called()
    subject.m.websocketSendMessage.assert_called_once()


@pytest.mark.parametrize('older_source', ['mic', 'speaker'])
def test_older_message_finishing_after_new_chat_skips_only_chatbox(subject, older_source):
    entered, release = Event(), Event()
    def translate(**request):
        if request['message'] == 'old private text':
            entered.set()
            assert release.wait(2)
        return 'translated ' + request['message']
    subject.m.translator.translate.side_effect = translate
    failures = []
    def old():
        try:
            getattr(subject.c, older_source + 'Message')({'text': 'old private text', 'language': 'English'})
        except Exception as error:
            failures.append(error)
    worker = Thread(target=old)
    worker.start()
    try:
        assert entered.wait(1)
        assert subject.c.chatMessage({'id': 'new', 'message': 'new'})['status'] == 200
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and not failures
    assert subject.m.oscSendMessage.call_count == 1
    assert 'new' in subject.m.oscSendMessage.call_args.args[0]
    assert subject.m.logger.info.call_count == 2
    assert subject.m.websocketSendMessage.call_count == 2
    assert subject.m.addTranslationHistory.call_count == 2
    assert subject.c.run.call_args.args[2]['original']['message'] == 'old private text'
    skip = [line for line in subject.process_logs if 'chatbox skipped' in line]
    assert len(skip) == 1 and 'private' not in skip[0]
    assert not notices(subject)


@pytest.mark.parametrize('source', ['chat', 'mic', 'speaker'])
def test_serial_same_source_messages_keep_their_order(subject, source):
    subject.m.translator.translate.side_effect = lambda **request: request['message']
    for text in ('first', 'second', 'third'):
        if source == 'chat':
            subject.c.chatMessage({'id': text, 'message': text})
        else:
            getattr(subject.c, source + 'Message')({'text': text, 'language': 'English'})
    assert [call.args[0].split('\n')[0] for call in subject.m.oscSendMessage.call_args_list] == ['first', 'second', 'third']


def test_failed_newer_osc_does_not_advance_watermark(subject):
    older = subject.m.chatbox_order.admit()
    newer = subject.m.chatbox_order.admit()
    with pytest.raises(RuntimeError):
        subject.m.chatbox_order.send(newer, Mock(side_effect=RuntimeError()), lambda: True)
    publish = Mock()
    assert subject.m.chatbox_order.send(older, publish, lambda: True)
    publish.assert_called_once()


@pytest.mark.parametrize('slot', ['1', '3'])
@pytest.mark.parametrize('change', [
    'none', 'target', 'translation-off', 'target-disabled', 'tab',
    'voice-slot', 'translation-off-on', 'unselected-target',
])
def test_blocked_mic_translation_rechecks_speech_settings_but_keeps_text_snapshot(app, change, slot):  # noqa: F811
    c, m, cfg = app.c, app.m, app.cfg
    cfg.SELECTED_TARGET_LANGUAGES['1']['1']['enable'] = False
    cfg.SELECTED_TARGET_LANGUAGES['1'][slot].update(enable=True, language='Japanese')
    before_targets = copy.deepcopy(cfg.SELECTED_TARGET_LANGUAGES['1'])
    c.voice_events.configure(VoiceSettings(mode='translated', mic_mode='translated', target_slot=slot))
    entered, release = Event(), Event()

    def translate(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return ['日本語の訳'], [True], ['translated']

    m.getInputTranslate.side_effect = translate
    session, delivery = start(app)
    session.emit('original')
    try:
        assert entered.wait(1)
        if change == 'target':
            cfg.SELECTED_TARGET_LANGUAGES['1'][slot]['language'] = 'French'
        elif change == 'translation-off':
            cfg.ENABLE_TRANSLATION = False
        elif change == 'target-disabled':
            cfg.SELECTED_TARGET_LANGUAGES['1'][slot]['enable'] = False
        elif change == 'tab':
            cfg.SELECTED_TARGET_LANGUAGES['2'] = copy.deepcopy(before_targets)
            cfg.SELECTED_TAB_NO = '2'
        elif change == 'voice-slot':
            c.voice_events.configure(VoiceSettings(mode='translated', mic_mode='translated', target_slot='2'))
        elif change == 'translation-off-on':
            c.setDisableTranslation()
            cfg.ENABLE_TRANSLATION = True
        elif change == 'unselected-target':
            cfg.SELECTED_TARGET_LANGUAGES['1']['2'].update(enable=True, language='French')
    finally:
        release.set()
    wait_for_finals(session, delivery)

    assert c.voice_events.status()['accepted'] == int(change in ('none', 'unselected-target'))
    translated = [item for item in captions(app) if item['state'] == 'translated']
    assert len(translated) == 1
    assert translated[0]['translations'] == [{'message': '日本語の訳', 'transliteration': []}]
    assert 'output_failures' not in translated[0]
    m.oscSendMessage.assert_called_once_with(c.messageFormatter(
        'SEND', ['日本語の訳'], 'original', cfg.SEND_MESSAGE_FORMAT_PARTS))
    ws = m.websocketSendMessage.call_args.args[0]
    assert ws['translation'] == ['日本語の訳']
    assert ws['dst_languages'] == before_targets
    overlay = m.publishRealtimeCaptionOverlay.call_args
    assert overlay.args[2] == before_targets
    m.logger.info.assert_called_once()
    m.addTranslationHistory.assert_called_once()
    assert not notices(app)


def test_realtime_admission_precedes_queue_and_keeps_snapshot_and_sequence(subject):
    session, delivery = start(subject)
    entered, release = Event(), Event()
    def translate(**request):
        if request['message'] == 'first':
            entered.set()
            assert release.wait(2)
        return 'translated ' + request['message']
    subject.m.translator.translate.side_effect = translate
    session.emit('first')
    assert entered.wait(1)
    try:
        session.emit('queued')
        assert session.idle.wait(1)
        assert subject.c.chatMessage({'id': 'new', 'message': 'typed'})['status'] == 200
        subject.cfg.SELECTED_TARGET_LANGUAGES['1']['1']['language'] = 'French'
        subject.cfg.ENABLE_TRANSLATION = False
    finally:
        release.set()
    wait_for_finals(session, delivery)
    assert subject.m.oscSendMessage.call_count == 1
    assert subject.m.logger.info.call_count == 3
    translated = [item for item in captions(subject) if item['state'] == 'translated']
    assert [item['translations'][0]['message'] for item in translated] == ['translated first', 'translated queued']
    calls = subject.m.publishRealtimeCaptionOverlay.call_args_list
    assert all(call.args[2]['1']['language'] == 'Japanese' for call in calls)
    subject.c.voice_events.publish.assert_called_once()
    event = subject.c.voice_events.publish.call_args.args[0]
    assert (event.source, event.target_language) == ('chat', 'Japanese')
    assert not notices(subject)


def test_realtime_overlay_failure_does_not_stop_final_processing(subject):
    subject.m.translator.translate.return_value = 'translated'
    subject.m.publishRealtimeCaptionOverlay.side_effect = RuntimeError('overlay')
    session, delivery = start(subject)
    session.emit('utterance')
    wait_for_finals(session, delivery)
    assert subject.m.oscSendMessage.call_count == 1
    assert subject.m.logger.info.call_count == 1
    assert captions(subject)[-1]['state'] == 'translated'
    assert notices(subject) and subject.c._realtime_errors['mic'] is None


def test_output_failure_inside_real_legacy_callback_keeps_worker_running(subject, monkeypatch):
    from model import MicSession
    from test_audio_pipeline_failure import _FakeRecorder, DEVICE

    recorder = _FakeRecorder()
    session = MicSession()
    session.transcript_fnc = subject.c.micMessage
    transcripts = []
    transcriber = Mock(last_recognition_error=False)
    transcriber.getAudioWaitTimeout.return_value = None
    transcriber.hasTranscript.side_effect = lambda: bool(transcripts)
    transcriber.getTranscript.side_effect = lambda: transcripts.pop(0)
    def transcribe(_, queue):
        queue.get_nowait()
        transcripts.append({'text': 'next utterance', 'language': 'English'})
    monkeypatch.setattr(session, '_create_recorder', lambda device: recorder)
    monkeypatch.setattr(session, '_create_transcriber', lambda: transcriber)
    monkeypatch.setattr(session, '_transcribe', transcribe)
    subject.m.translator.translate.return_value = 'translated'
    subject.m.createOverlayImageLargeLog.side_effect = RuntimeError('overlay')
    received = Event()
    subject.m.addTranslationHistory.side_effect = lambda *args: received.set()
    try:
        session.reconfigure(transcript=True, device=DEVICE)
        for _ in range(2):
            received.clear()
            recorder.audio_queue.put((b'\0\0', None))
            assert received.wait(1)
        assert session.features == {'transcript'}
        assert not session._pipeline_error_started
        recorder.stop.assert_not_called()
        assert len(notices(subject)) == 2
    finally:
        session.stop_for_handoff()


def test_failure_notification_itself_cannot_stop_legacy_outputs(subject):
    subject.m.translator.translate.return_value = 'translated'
    subject.m.createOverlayImageLargeLog.side_effect = RuntimeError('overlay')
    subject.c.run.side_effect = RuntimeError('IPC unavailable')
    subject.c.micMessage({'text': 'original', 'language': 'English'})
    subject.m.websocketSendMessage.assert_called_once()
    subject.m.logger.info.assert_called_once()
    subject.m.addTranslationHistory.assert_called_once()
    assert subject.cfg.ENABLE_TRANSCRIPTION_SEND


def test_late_translation_failure_preserves_newer_language_selection(subject):
    subject.c.changeToCTranslate2Process = module.Controller.changeToCTranslate2Process.__get__(subject.c)
    before = subject.cfg.SELECTED_TRANSLATION_ENGINES.copy()
    def translate(**kwargs):
        subject.cfg.SELECTED_TAB_NO = '2'
        return False if kwargs["translator_name"] == "OpenAI_API" else None
    # A real failure followed by unsupported fallback retains failure status.
    subject.m.translator.translate.side_effect = translate
    result = subject.c.chatMessage({'id': 'late', 'message': 'original'})
    assert result['status'] == 200
    assert subject.cfg.SELECTED_TRANSLATION_ENGINES == before


@pytest.mark.parametrize('slot,spoken', [('1', False), ('2', True)])
def test_chat_tts_checks_only_the_selected_targets_provenance(subject, slot, spoken):
    subject.cfg.SELECTED_TARGET_LANGUAGES['1']['2'].update(enable=True, language='Korean', country='South Korea')
    subject.c.voice_events.configure(VoiceSettings(mode='translated', target_slot=slot))
    subject.m.translator.translate.side_effect = lambda **request: '한국어' if request['target_language'] == 'Korean' else False
    result = subject.c.chatMessage({'id': 'multiple', 'message': 'original'})
    assert [entry['message'] for entry in result['result']['translations']] == ['original', '한국어']
    assert subject.c.voice_events.publish.called is spoken
    if spoken:
        event = subject.c.voice_events.publish.call_args.args[0]
        assert (event.translated_text, event.target_language) == ('한국어', 'Korean')
