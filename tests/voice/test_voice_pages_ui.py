"""Real settings navigation, forms and response hooks; model-free stdio peer."""
import base64
import json
import os
from urllib.parse import urlsplit

import pytest
from models.tts.settings import VoiceSettings
from test_speech_servers_ui import ui

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_SPEECH_UI') != '1', reason='opt-in browser integration')


@pytest.fixture
def pages(ui):
    page, peer, reply = ui
    peer.reject_voice = False
    peer.hold_voice = False
    peer.sequence = 0
    peer.tts = dict(tts_enabled=False, tts_generation=0, active=False, queued=0)
    peer.hold_tts = False
    peer.hold_direct = False
    peer.reject_tts = None
    peer.direct = dict(generation=0, requested=False, pending=False, active=False, mode='off', error=None,
                       settings=dict(mode='passthrough', engine='seed-vc', runtime='', reference='',
                                     rvc_runtime='', rvc_model='', rvc_index='', rvc_pitch=0, rvc_index_rate=0))
    peer.sources = [dict(label='Test microphone', id=dict(cookie='test-cookie', serial=15,
                        name='physical-source', media_class='Audio/Source'))]

    def write(line):
        req = json.loads(line)
        ep = req['endpoint']
        data = json.loads(base64.b64decode(req['data'])) if req.get('data') else None
        peer.sequence += 1
        observation = str(peer.sequence)
        peer.sent.append((ep, data))
        if ep == '/get/data/voice_status':
            reply(ep, dict(peer.tts, observation_id=observation))
        elif ep in ('/run/enable_tts', '/run/disable_tts'):
            if ep == '/run/enable_tts' and peer.reject_tts:
                reply(ep, dict(error_code=peer.reject_tts), 409)
            elif ep == '/run/disable_tts' or not peer.hold_tts:
                peer.tts.update(tts_enabled=ep == '/run/enable_tts', tts_generation=peer.tts['tts_generation'] + 1)
                reply(ep, dict(peer.tts, observation_id=observation))
        elif ep in ('/run/start_direct_voice', '/run/stop_direct_voice'):
            if ep == '/run/stop_direct_voice' or not peer.hold_direct:
                enabled = ep == '/run/start_direct_voice'
                peer.direct.update(requested=enabled, active=enabled, pending=False, mode='converted' if enabled else 'off', generation=peer.direct['generation'] + 1)
                reply(ep, dict(peer.direct, observation_id=observation))
        elif ep == '/get/data/voice_route':
            reply(ep, dict(observation_id=observation, managed=peer.voice['routing'] == 'managed', ready=True,
                           requested_muted=False, observed_muted=False))
        elif ep == '/get/data/direct_voice_state':
            reply(ep, dict(peer.direct, observation_id=observation))
        elif ep == '/get/data/direct_voice_sources':
            reply(ep, dict(sources=peer.sources, error=None))
        elif ep == '/get/data/voice_output_devices':
            reply(ep, dict(devices=[dict(id='headphones', label='Headphones')], error=None))
        elif ep == '/set/data/voice_settings':
            if peer.reject_voice:
                reply(ep, dict(error_code='VOICE_SETTINGS_INVALID'), 400)
            elif not peer.hold_voice:
                peer.voice = VoiceSettings.from_dict(data).to_dict()
                reply(ep, peer.voice)
        elif ep == '/set/data/direct_voice_settings':
            peer.direct['settings'] = data
            reply(ep, dict(peer.direct, observation_id=observation))
        else:
            # Existing speech/ASR fixture handles the other production endpoints.
            peer.sent.pop()
            return False
        return True

    page.expose_function('voiceHandled', write)
    page.add_init_script('window.voiceWrite = async line => { if (!await window.voiceHandled(line)) await window.sidecarWrite(line); };')
    base = urlsplit(page.url)
    page.goto(f'{base.scheme}://{base.netloc}/tests/voice/voice-pages-entry/')
    yield page, peer, reply


def test_separate_pages_search_and_asr_placement(pages):
    from playwright.sync_api import expect
    page, peer, _ = pages
    expect(page.get_by_role('button', name='TTS', exact=True)).to_be_visible()
    expect(page.get_by_label('Chat voice', exact=True)).to_be_visible()
    expect(page.get_by_role('group', name='ASR + VAD', exact=True)).to_have_count(0)
    page.get_by_role('button', name='RVC', exact=True).click()
    expect(page.get_by_label('Permitted RVC model (.pth)', exact=True)).to_be_visible()
    expect(page.get_by_label('Chat voice', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Advanced', exact=True).click()
    expect(page.get_by_label('Permitted RVC model (.pth)', exact=True)).to_have_count(0)
    expect(page.get_by_label('Chat voice', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Transcription', exact=True).click()
    expect(page.get_by_role('group', name='ASR + VAD', exact=True)).to_be_visible()
    expect(page.get_by_role('group', name='Japanese TTS', exact=True)).to_have_count(0)
    page.get_by_label('Search settings', exact=True).fill('RVC')
    page.get_by_label('Search results', exact=True).get_by_role('button').first.click()
    expect(page.get_by_label('Permitted RVC model (.pth)', exact=True)).to_be_visible()
    assert not any(ep.startswith('/run/start_') for ep, _ in peer.sent)


def test_unsaved_changes_require_ack_and_navigation_confirmation(pages):
    from playwright.sync_api import expect
    page, peer, reply = pages
    mode = page.get_by_label('Chat voice', exact=True)
    mode.select_option('original')
    page.get_by_label('Output device', exact=True).select_option('headphones')
    save = page.get_by_role('button', name='Save voice settings', exact=True)
    peer.reject_voice = True
    save.click()
    expect(page.get_by_role('alert').filter(has_text='VOICE_SETTINGS_INVALID')).to_be_visible()
    expect(mode).to_have_value('original')
    page.get_by_role('button', name='RVC', exact=True).click()
    page.get_by_role('button', name='Keep editing', exact=True).click()
    expect(mode).to_be_visible()
    peer.reject_voice = False
    peer.hold_voice = True
    save.click()
    expect(page.get_by_role('button', name='Saving…', exact=True)).to_be_disabled()
    peer.voice = VoiceSettings.from_dict(dict(peer.voice, mode='original', output_device='headphones')).to_dict()
    reply('/set/data/voice_settings', peer.voice)
    expect(save).to_be_disabled()
    page.get_by_role('button', name='RVC', exact=True).click()
    expect(page.get_by_label('Permitted RVC model (.pth)', exact=True)).to_be_visible()


def test_input_identity_survives_pages_and_stale_state(pages):
    from playwright.sync_api import expect
    page, peer, reply = pages
    page.get_by_role('button', name='RVC', exact=True).click()
    source = page.get_by_label('Input to forward', exact=True)
    source.select_option(label='Test microphone')
    identity = source.input_value()
    page.get_by_role('button', name='TTS', exact=True).click()
    page.get_by_role('button', name='RVC', exact=True).click()
    expect(source).to_have_value(identity)
    assert json.loads(identity) == ['test-cookie', 15, 'physical-source', 'Audio/Source']
    peer.direct.update(requested=True, pending=True, mode='converted')
    peer.direct['settings'].update(mode='converted', engine='rvc')
    reply('/get/data/direct_voice_state', dict(peer.direct, observation_id='100000'))
    expect(source).to_be_disabled()
    received = reply('/get/data/direct_voice_state', dict(peer.direct, requested=False, pending=False, observation_id='1'))
    page.wait_for_function('id => window.received.includes(id)', arg=received)
    expect(source).to_be_disabled()
    page.get_by_role('button', name='Device', exact=True).click()
    expect(page.get_by_role('combobox', name='Audio route', exact=True)).to_be_disabled()
