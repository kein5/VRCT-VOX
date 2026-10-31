"""Production forms/hooks/IPC routes, with a deterministic stdio process peer."""
import base64
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest

from models.speech_server.settings import normalize_settings
from models.transcription.realtime_settings import normalize_settings as asr_settings
from models.tts.settings import VoiceSettings

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_SPEECH_UI') != '1', reason='opt-in browser integration')


def test_low_latency_default_opt_in_save_and_busy_controls(ui):
    from playwright.sync_api import expect
    page, peer, reply = ui
    toggle = page.get_by_label('Low-latency standby (Irodori GPU)', exact=True)
    expect(toggle).not_to_be_checked()
    toggle.check()
    page.get_by_role('button', name='Save server settings', exact=True).click()
    expect(page.get_by_role('button', name='Save server settings', exact=True)).to_be_disabled()
    assert peer.settings['profiles']['japanese']['low_latency'] is True
    assert not any(ep == '/run/start_speech_server' for ep, _ in peer.sent)
    peer.state['japanese'].update(state='ready', generation=1,
        low_latency=dict(state='ready', completed=1, error_code=None))
    reply('/get/data/speech_server_state', peer.state)
    expect(page.get_by_text('Low-latency standby active', exact=True)).to_be_visible()
    # Engine settings can be collapsed while ready; property is still disabled.
    expect(toggle).to_be_disabled()


@pytest.fixture
def ui(tmp_path):
    from playwright.sync_api import sync_playwright
    with ExitStack() as stack:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        log = stack.enter_context((tmp_path / 'vite.log').open('w'))
        vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '.', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=ROOT, stdout=log, stderr=log)

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
        browser = stack.enter_context(sync_playwright()).chromium.launch(executable_path=os.environ['VRCT_TEST_CHROMIUM'], headless=True)
        stack.callback(browser.close)
        page = browser.new_page(viewport={'width': 1200, 'height': 1600})
        stack.callback(lambda: (tmp_path / 'page.html').write_text(page.content()))
        page.set_default_timeout(4000)
        peer = SimpleNamespace(settings=normalize_settings({}), voice=VoiceSettings().to_dict(), asr=asr_settings({}),
                               state={name: dict(state='stopped', generation=0, base_url=None, error_code=None) for name in ('japanese', 'multilingual', 'asr')},
                               sent=[], replies=[], errors=[], reply_id=0, hold_start=False, reject_save=False)
        page.on('pageerror', lambda error: peer.errors.append(str(error)))

        def reply(endpoint, result, status=200):
            peer.reply_id += 1
            peer.replies.append(json.dumps(dict(endpoint=endpoint, status=status, result=result, _test_reply_id=peer.reply_id)))
            return peer.reply_id

        def write(line):
            request = json.loads(line)
            endpoint = request['endpoint']
            data = json.loads(base64.b64decode(request['data'])) if request.get('data') else None
            peer.sent.append((endpoint, data))
            if endpoint == '/get/data/speech_server_settings':
                reply(endpoint, peer.settings)
            elif endpoint == '/set/data/speech_server_settings':
                if peer.reject_save:
                    reply(endpoint, dict(error_code='speech_server_settings_invalid'), 400)
                else:
                    peer.settings = normalize_settings(data)
                    reply(endpoint, peer.settings)
            elif endpoint == '/get/data/speech_server_state':
                reply(endpoint, peer.state)
            elif endpoint == '/run/start_speech_server':
                if not peer.hold_start:
                    row = peer.state[data['profile']]
                    row.update(state='preparing', generation=row['generation'] + 1)
                    reply(endpoint, peer.state)
            elif endpoint == '/run/stop_speech_server':
                row = peer.state[data['profile']]
                row.update(state='stopped', generation=row['generation'] + 1, base_url=None)
                reply(endpoint, peer.state)
            elif endpoint == '/get/data/voice_settings':
                reply(endpoint, peer.voice)
            elif endpoint == '/set/data/voice_settings':
                peer.voice = VoiceSettings.from_dict(data).to_dict()
                reply(endpoint, peer.voice)
            elif endpoint == '/get/data/realtime_asr_settings':
                reply(endpoint, peer.asr)
            elif endpoint == '/set/data/realtime_asr_settings':
                peer.asr = asr_settings(data)
                reply(endpoint, peer.asr)
            elif endpoint == '/get/data/realtime_asr_models':
                bundled = peer.asr['server'] == 'bundled'
                row = peer.state['asr']
                reply(endpoint, dict(server=peer.asr['server'], configured_url=peer.asr['base_url'],
                    base_url=row['base_url'] if bundled else peer.asr['base_url'], server_generation=row['generation'] if bundled else None,
                    models=[] if bundled and row['state'] != 'ready' else [dict(id='bundled-asr' if bundled else 'external-asr', languages=['ja'], accepts_language=False)], error_code=None))
            elif endpoint == '/get/data/realtime_asr_state':
                reply(endpoint, {source: dict(state='idle', generation=0, requested=False) for source in ('mic', 'speaker')})

        def read():
            result = list(peer.replies)
            peer.replies.clear()
            return result

        page.expose_function('sidecarWrite', write)
        page.expose_function('sidecarRead', read)
        pending_requests = set()
        page.on('request', lambda request: pending_requests.add(request.url))
        page.on('requestfinished', lambda request: pending_requests.discard(request.url))
        page.on('requestfailed', lambda request: pending_requests.discard(request.url))
        try:
            page.goto(f'http://127.0.0.1:{port}/tests/voice/speech-ui-entry/')
        except Exception:
            print('Unfinished navigation resources:', sorted(pending_requests))
            print('Document state:', page.evaluate('document.readyState'))
            raise
        yield page, peer, reply
        assert not peer.errors


def test_save_only_explicit_start_pending_stop_and_stale_ready(ui):
    from playwright.sync_api import expect
    page, peer, reply = ui
    group = page.get_by_role('group', name='Japanese TTS', exact=True)
    start = group.get_by_role('button', name='Start server', exact=True)
    expect(start).to_be_disabled()
    group.get_by_label('Model GGUF path', exact=True).fill('/local/tts.gguf')
    expect(start).to_be_disabled()
    save = page.get_by_role('button', name='Save server settings', exact=True)
    save.click()
    expect(start).to_be_enabled()
    assert not any(ep == '/run/start_speech_server' for ep, _ in peer.sent)
    peer.hold_start = True
    start.click()
    expect(start).to_be_disabled()
    assert ('/run/start_speech_server', dict(profile='japanese', generation=0)) in peer.sent
    group.get_by_role('button', name='Stop server', exact=True).click()
    expect(start).to_be_enabled()
    # A delayed success for an older Start cannot resurrect the UI.
    old = copy.deepcopy(peer.state)
    old['japanese'].update(state='ready', generation=0, base_url='http://127.0.0.1:12345')
    received = reply('/run/start_speech_server', old)
    page.wait_for_function('id => window.received.includes(id)', arg=received)
    expect(group.get_by_role('status')).to_have_text('Stopped')
    peer.hold_start = False
    start.click()
    expect(group.get_by_role('status')).to_have_text('Loading model')
    expect(start).to_be_disabled()
    peer.state['japanese'].update(state='ready', base_url='http://127.0.0.1:12345')
    reply('/get/data/speech_server_state', peer.state)
    expect(group.get_by_role('status')).to_have_text('Ready')
    late = copy.deepcopy(peer.state)
    late['japanese']['state'] = 'preparing'
    received = reply('/get/data/speech_server_state', late)
    page.wait_for_function('id => window.received.includes(id)', arg=received)
    expect(group.get_by_role('status')).to_have_text('Ready')
    peer.state['japanese'].update(state='failed', generation=3, base_url=None, error_code='speech_server_exited')
    reply('/get/data/speech_server_state', peer.state)
    expect(group.get_by_role('alert')).to_contain_text('speech_server_exited')
    expect(start).to_be_enabled()


def test_memory_error_explains_cpu_retry_and_preserves_saved_device(ui):
    from playwright.sync_api import expect
    page, peer, reply = ui
    group = page.get_by_role('group', name='Japanese TTS', exact=True)
    group.get_by_label('Model GGUF path', exact=True).fill('/local/tts.gguf')
    page.get_by_role('button', name='Save server settings', exact=True).click()
    peer.state['japanese'].update(state='failed', generation=3, base_url=None,
                                error_code='speech_server_out_of_memory')
    reply('/get/data/speech_server_state', peer.state)
    expect(group.get_by_role('alert')).to_contain_text('Not enough memory')
    expect(group.get_by_role('alert')).to_contain_text('CPU')
    expect(group.get_by_role('alert')).to_contain_text('speech_server_out_of_memory')
    expect(group.get_by_label('Inference device', exact=True)).to_have_value('auto')
    group.get_by_label('Inference device', exact=True).select_option('cpu')
    start = group.get_by_role('button', name='Start server', exact=True)
    expect(start).to_be_disabled()
    page.get_by_role('button', name='Save server settings', exact=True).click()
    expect(start).to_be_enabled()
    assert peer.settings['profiles']['japanese']['device'] == 'cpu'
    assert not any(ep == '/run/start_speech_server' for ep, _ in peer.sent)


def test_asr_requires_vad_and_save_errors_allow_retry(ui):
    from playwright.sync_api import expect
    page, peer, _ = ui
    group = page.get_by_role('group', name='ASR + VAD', exact=True)
    start = group.get_by_role('button', name='Start server', exact=True)
    group.get_by_label('Model GGUF path', exact=True).fill('/local/asr.gguf')
    page.get_by_role('button', name='Save server settings', exact=True).click()
    expect(start).to_be_disabled()
    group.get_by_label('VAD GGUF path', exact=True).fill('/local/vad.gguf')
    peer.reject_save = True
    save = page.get_by_role('button', name='Save server settings', exact=True)
    save.click()
    expect(page.get_by_role('alert').filter(has_text='speech_server_settings_invalid')).to_be_visible()
    expect(save).to_be_enabled()
    peer.reject_save = False
    save.click()
    expect(start).to_be_enabled()
    assert not any(ep == '/run/start_speech_server' for ep, _ in peer.sent)


def test_endpoint_selection_retains_external_urls_and_rejects_old_model_lists(ui):
    from playwright.sync_api import expect
    page, peer, reply = ui
    page.get_by_label('Japanese server', exact=True).select_option('bundled')
    expect(page.get_by_label('Japanese server (Irodori)', exact=True)).to_have_count(0)
    page.get_by_role('button', name='Save voice settings', exact=True).click()
    page.get_by_label('Japanese server', exact=True).select_option('external')
    expect(page.get_by_label('Japanese server (Irodori)', exact=True)).to_have_value('http://127.0.0.1:8080')
    page.get_by_label('ASR server', exact=True).select_option('bundled')
    page.get_by_role('button', name='Save caption settings', exact=True).click()
    model = page.get_by_label('ASR model', exact=True)
    expect(model.locator('option[value="external-asr"]')).to_have_count(0)
    peer.state['asr'].update(state='ready', generation=4, base_url='http://127.0.0.1:12345')
    reply('/get/data/speech_server_state', peer.state)
    expect(model.locator('option[value="bundled-asr"]')).to_have_count(1)
    received = reply('/get/data/realtime_asr_models', dict(server='external', configured_url=peer.asr['base_url'], base_url=peer.asr['base_url'], models=[dict(id='stale', languages=['ja'])]))
    page.wait_for_function('id => window.received.includes(id)', arg=received)
    expect(model.locator('option[value="stale"]')).to_have_count(0)
    # Same OS port may be reused on restart; generation still has to match.
    received = reply('/get/data/realtime_asr_models', dict(server='bundled', configured_url=peer.asr['base_url'], base_url=peer.state['asr']['base_url'], server_generation=2, models=[dict(id='stale', languages=['ja'])]))
    page.wait_for_function('id => window.received.includes(id)', arg=received)
    expect(model.locator('option[value="stale"]')).to_have_count(0)
