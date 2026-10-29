"""Native ASR transport -> translation -> OSC continues with TTS disabled.

Recognition/translation/TTS servers are deterministic local peers. Capture,
Controller, delivery, OSC, scheduler and output are production code on a private
PipeWire graph. This does not evaluate model quality or capture a physical mic.
"""
from contextlib import ExitStack
import json
import os
from queue import Queue, Empty
import socket
import sys
from threading import Thread
import time

import pytest
from websockets.sync.server import serve
from websockets.exceptions import ConnectionClosed

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state
from test_native_realtime import TranslationFixture
from models.transcription.capture_pipewire import enumerate_endpoints
from models.transcription.realtime_settings import endpoint_dict, normalize_settings
from tools.voice_acceptance import loopback, private_graph, wait_for
from tools.voice_b_poc import Producer

pytestmark = pytest.mark.skipif(os.environ.get('VRCT_TEST_NATIVE_TTS_INDEPENDENCE') != '1', reason='opt-in native private graph')


class RecognitionPeer:
    def __enter__(self):
        self.finals = Queue()
        self.audio_chunks = 0
        def request(connection, request):
            if request.path == '/v1/models':
                response = connection.respond(200, json.dumps({'data': [{'id': 'fixture-asr', 'speech': {
                    'task': 'recognition', 'languages': ['ja'], 'options': [{'name': 'language'}]}}]}))
                del response.headers['Content-Type']
                response.headers['Content-Type'] = 'application/json'
                return response
        def handler(ws):
            try:
                ws.send(json.dumps({'event_id': 'created', 'type': 'session.created',
                                    'session': {'type': 'transcription', 'id': 'fixture-session'}}))
                config = json.loads(ws.recv())
                ws.send(json.dumps({'event_id': 'configured', 'type': 'session.updated',
                                    'session': {'id': 'fixture-session', **config['session']}}))
                for raw in ws:
                    if json.loads(raw)['type'] != 'input_audio_buffer.append':
                        continue
                    self.audio_chunks += 1
                    try:
                        item = self.finals.get_nowait()
                    except Empty:
                        continue
                    ws.send(json.dumps({'event_id': f'start-{item}', 'type': 'input_audio_buffer.speech_started', 'item_id': str(item)}))
                    ws.send(json.dumps({'event_id': f'final-{item}', 'type': 'conversation.item.input_audio_transcription.completed',
                                        'item_id': str(item), 'transcript': f'確定文{item}', 'stop': 'complete'}))
            except ConnectionClosed:
                pass
        self.server = serve(handler, '127.0.0.1', 0, process_request=request)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.socket.getsockname()[1]}'
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join(3)


def test_tts_off_keeps_asr_translation_and_osc(tmp_path):
    sys.path.insert(0, str(ROOT / 'tests/voice'))
    from ui_entry_acceptance import FixtureServer
    from pythonosc.osc_packet import OscPacket
    with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
        loopback(stack, 'vrct.independence')
        Producer(stack, 'vrct.independence.sink', 440)
        recognition = stack.enter_context(RecognitionPeer())
        translation = stack.enter_context(TranslationFixture(['First translation', 'Second translation', 'Third translation']))
        tts = FixtureServer()
        tts.start()
        stack.callback(tts.stop)
        osc = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        osc.bind(('127.0.0.2', 0))
        osc.setblocking(False)
        asr = normalize_settings({'base_url': recognition.url, 'model': 'fixture-asr'})
        asr['mic']['endpoint'] = endpoint_dict(next(row['endpoint'] for row in enumerate_endpoints('mic')
                                                   if row['endpoint'].name == 'vrct.independence.source'))
        state = initial_state(tmp_path)
        config = state / 'config.json'
        values = json.loads(config.read_text())
        values.update(REALTIME_ASR_SETTINGS=asr, LMSTUDIO_URL=translation.url,
                      SELECTED_TRANSLATION_ENGINES={str(tab): 'LMStudio' for tab in range(1, 6)},
                      SEND_MESSAGE_TO_VRC=True, OSC_PORT=osc.getsockname()[1],
                      VOICE_SETTINGS={'routing': 'managed', 'mic_mode': 'translated', 'direct_policy': 'mix',
                                      'multilingual_url': tts.url})
        config.write_text(json.dumps(values))
        with NativeWebDriver(tmp_path / 'ui', {'VRCT_CONFIG_DIR': str(state)}) as ui:
            ui.wait("return document.querySelector('textarea[class*=message_box_input_area]') !== null")
            ui.open_route_settings()
            ui.click_text('button', 'Resume voice')
            ui.open_voice_page('Transcription', 'section[aria-label="Realtime captions"] select')
            ui.click_text('button', 'Start microphone captions')
            ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Captions running')")
            ui.close_settings()
            ui.click('[role=switch][aria-label=Translation]')
            ui.wait("return document.querySelector('[role=switch][aria-label=Translation]').getAttribute('aria-checked') === 'true'")
            ui.click('[role=switch][aria-label=TTS]')
            ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-checked') === 'true'")
            for item, tts_count in ((1, 1), (2, 1), (3, 2)):
                recognition.finals.put(item)
                wait_for(lambda: len(translation.requests) == item)
                ui.wait(f"return document.querySelector('#log_container').innerText.includes({json.dumps(['First', 'Second', 'Third'][item-1] + ' translation')})")
                wait_for(lambda: len(tts.requests) == tts_count)
                if item < 3:
                    ui.click('[role=switch][aria-label=TTS]')
                    ui.wait("return document.querySelector('[role=switch][aria-label=TTS]').getAttribute('aria-busy') === 'false'")
                if item == 2:
                    assert len(tts.requests) == 1
            messages = []
            deadline = time.monotonic() + 5
            while len(messages) < 3 and time.monotonic() < deadline:
                try:
                    messages.extend(t.message.params[0] for t in OscPacket(osc.recv(65536)).messages if t.message.address == '/chatbox/input')
                except BlockingIOError:
                    time.sleep(.02)
            assert len(messages) == 3
            assert all(sum(word in text for text in messages) == 1 for word in ['First translation', 'Second translation', 'Third translation'])
            assert recognition.audio_chunks > 0
            assert len(tts.requests) == 2
            ui.click_text('button', 'Stop microphone captions')
            ui.close_app()
        (tmp_path / 'independence.json').write_text(json.dumps(dict(translation_count=3, osc_count=3,
            tts_count=2, asr_audio_chunks=recognition.audio_chunks, real_models=False, physical_capture=False), indent=2))
