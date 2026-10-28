"""Opt-in browser test of production React/hooks/routes with a fake stdio peer.

Only IPC is substituted. Audio and native Tauri are covered separately.
"""
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from models.tts.settings import VoiceSettings
from models.voice_conversion.settings import DirectSettings

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_DIRECT_UI') != '1', reason='opt-in browser integration')
ID = {'cookie': '42', 'serial': '18446744073709551615', 'name': 'external.source', 'media_class': 'Audio/Source'}


def test_explicit_selection_no_rebind_and_stale_response_ordering(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    chromium = os.environ['VRCT_TEST_CHROMIUM']
    with ExitStack() as stack:
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        log = stack.enter_context((tmp_path / 'vite.log').open('w'))
        vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1',
                                 '--port', str(port), '--strictPort'], cwd=ROOT, stdout=log, stderr=log)
        def close_vite():
            vite.terminate()
            try:
                vite.wait(5)
            except subprocess.TimeoutExpired:
                vite.kill()
                vite.wait(3)
        stack.callback(close_vite)
        deadline = time.monotonic() + 15
        while 'Local:' not in (tmp_path / 'vite.log').read_text():
            assert vite.poll() is None and time.monotonic() < deadline
            time.sleep(.05)
        browser = stack.enter_context(sync_playwright()).chromium.launch(executable_path=chromium, headless=True)
        stack.callback(browser.close)
        page = browser.new_page(viewport={'width': 1200, 'height': 1200})
        page.set_default_timeout(4000)
        errors, sent, replies = [], [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        sources = {'sources': [{'id': ID, 'label': 'External voice'}], 'error': None}
        state = {'source': None, 'requested': False, 'active': False, 'pending': False, 'error': None,
                 'generation': 0, 'conversion_verified': False, 'observation_id': '10',
                 'settings': DirectSettings().to_dict(), 'mode': 'off'}
        voice_settings = VoiceSettings(routing='managed').to_dict()
        def reply(endpoint, result, status=200):
            replies.append(json.dumps({'endpoint': endpoint, 'status': status, 'result': result}))
        def write(line):
            request = json.loads(line)
            sent.append(request)
            endpoint = request['endpoint']
            values = {
                '/get/data/voice_settings': voice_settings,
                '/get/data/voice_route': {'managed': True, 'ready': True, 'observed_muted': True,
                                        'requested_muted': True, 'pending': False, 'observation_id': '1'},
                '/get/data/voice_status': {}, '/get/data/voice_output_devices': {'devices': [], 'error': None},
                '/get/data/direct_voice_sources': sources, '/get/data/direct_voice_state': state,
            }
            if endpoint in values:
                reply(endpoint, values[endpoint])
            elif endpoint == '/set/data/direct_voice_settings':
                saved = DirectSettings.from_dict(json.loads(base64.b64decode(request['data']))).to_dict()
                state.update(settings=saved, observation_id=str(int(state['observation_id'])+10))
                reply(endpoint, dict(state))
            elif endpoint == '/set/data/voice_settings':
                saved = VoiceSettings.from_dict(json.loads(base64.b64decode(request['data']))).to_dict()
                voice_settings.clear()
                voice_settings.update(saved)
                reply(endpoint, saved)
        def read():
            result = list(replies)
            replies.clear()
            return result
        page.expose_function('sidecarWrite', write)
        page.expose_function('sidecarRead', read)
        page.goto(f'http://127.0.0.1:{port}/tests/voice/ui-entry/')
        mic_speech = page.get_by_role('combobox', name='Realtime microphone speech', exact=True)
        expect(mic_speech).to_have_value('off')
        mic_speech.select_option('translated')
        policy = page.get_by_role('combobox', name='Direct input while translating', exact=True)
        expect(policy).to_have_value('suppress')
        policy.select_option('mix')
        page.get_by_role('button', name='Save voice settings', exact=True).click()
        expect(page.get_by_role('button', name='Save voice settings', exact=True)).to_be_enabled()
        assert voice_settings['mic_mode'] == 'translated' and voice_settings['direct_policy'] == 'mix'
        assert not any(r['endpoint'].startswith('/run/start') for r in sent)
        page.reload()
        expect(mic_speech).to_have_value('translated')
        expect(policy).to_have_value('mix')
        assert not any(r['endpoint'].startswith('/run/start') for r in sent)
        selector = page.get_by_role('combobox', name='Input to forward', exact=True)
        expect(selector).to_be_visible()  # RED: current application has no input forwarding UI
        start = page.get_by_role('button', name='Start input forwarding', exact=True)
        stop = page.get_by_role('button', name='Stop input forwarding', exact=True)
        expect(start).to_be_disabled()
        selected_value = selector.locator('option').filter(has_text='External voice').get_attribute('value')
        selector.select_option(selected_value)
        expect(start).to_be_enabled()
        assert not any(r['endpoint'] == '/run/start_direct_voice' for r in sent)
        start.click()
        page.wait_for_timeout(50)
        request = next(r for r in sent if r['endpoint'] == '/run/start_direct_voice')
        assert json.loads(base64.b64decode(request['data'])) == {'source': ID}
        running = {**state, 'source': ID, 'requested': True, 'active': True, 'generation': 1, 'observation_id': '20'}
        reply('/run/start_direct_voice', running)
        expect(page.get_by_text('Input forwarding connected', exact=True)).to_be_visible()
        expect(start).to_be_disabled()
        stop.click()
        stopped = {**state, 'source': ID, 'generation': 2, 'observation_id': '30'}
        state.update(stopped)
        reply('/run/stop_direct_voice', stopped)
        expect(page.get_by_text('Input forwarding stopped', exact=True)).to_be_visible()
        reply('/get/data/direct_voice_state', running)  # delayed active snapshot
        page.wait_for_timeout(100)
        expect(page.get_by_text('Input forwarding stopped', exact=True)).to_be_visible()
        sources['sources'] = [{'id': {**ID, 'serial': '18446744073709551614'}, 'label': 'External voice'}]
        page.get_by_role('button', name='Refresh inputs', exact=True).click()
        expect(selector.locator('option:checked')).to_contain_text('Disconnected')
        expect(start).to_be_disabled()
        replacement = selector.locator('option').filter(has_text='External voice').get_attribute('value')
        selector.select_option(replacement)
        expect(start).to_be_enabled()
        start.click()
        reply('/run/start_direct_voice', {'error_code': 'source_bridge_stale_start'}, 409)
        expect(page.get_by_role('alert').filter(has_text='source_bridge_stale_start')).to_be_visible()
        expect(page.get_by_text('Input forwarding stopped', exact=True)).to_be_visible()
        mode = page.get_by_role('combobox', name='Direct voice mode', exact=True)
        mode.select_option('converted')
        page.get_by_role('textbox', name='Seed runtime folder', exact=True).fill('/allowed/runtime')
        page.get_by_role('textbox', name='Permitted reference WAV', exact=True).fill('/allowed/reference.wav')
        expect(start).to_be_disabled()  # Unsaved intent cannot start a different producer.
        page.get_by_role('button', name='Save input settings', exact=True).click()
        expect(start).to_be_enabled()
        assert len([r for r in sent if r['endpoint'] == '/run/start_direct_voice']) == 2
        page.reload()
        expect(mode).to_have_value('converted')
        expect(page.get_by_role('textbox', name='Seed runtime folder', exact=True)).to_have_value('/allowed/runtime')
        expect(start).to_be_disabled()  # Input selection is never restored.
        selector.select_option(replacement)
        start.click()
        page.wait_for_timeout(50)
        payload = json.loads(base64.b64decode([r for r in sent if r['endpoint'] == '/run/start_direct_voice'][-1]['data']))
        assert payload == {'source': sources['sources'][0]['id'], 'mode': 'converted',
                           'options': {'runtime': '/allowed/runtime', 'reference': '/allowed/reference.wav'}}
        vc_ready = {**state, 'mode': 'converted', 'conversion_state': 'ready',
                    'active': True, 'requested': True, 'conversion_verified': False, 'observation_id': '50'}
        reply('/run/start_direct_voice', vc_ready)
        expect(page.get_by_text('VC ready; conversion not yet confirmed', exact=True)).to_be_visible()
        expect(mode).to_be_disabled()
        reply('/get/data/direct_voice_state', {**vc_ready, 'conversion_state': 'converted',
               'conversion_verified': True, 'observation_id': '60'})
        expect(page.get_by_text('Converting voice', exact=True)).to_be_visible()
        stop.click()
        state.update(mode='off', requested=False, active=False, observation_id='70')
        reply('/run/stop_direct_voice', dict(state))
        expect(page.get_by_text('Input forwarding stopped', exact=True)).to_be_visible()
        sources.update(sources=[], error='source_bridge_linux_only')
        page.get_by_role('button', name='Refresh inputs', exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='source_bridge_linux_only')).to_be_visible()
        expect(start).to_be_disabled()
        assert len([r for r in sent if r['endpoint'] == '/run/start_direct_voice']) == 3
        assert not any(r['endpoint'] == '/run/resume_voice' for r in sent)
        assert not errors, errors
