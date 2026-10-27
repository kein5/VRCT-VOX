"""Opt-in real Tauri/Controller to private PipeWire; synthetic audio only.

Tests explicit passthrough and independent stops, not real conversion/inference.
No physical microphone, host graph, model downloads, or raw audio artifacts.
"""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread
import time

import pytest

from native_webdriver import NativeWebDriver, ROOT
from test_native_ui import initial_state

pytestmark = pytest.mark.skipif(
    sys.platform != 'linux' or os.environ.get('VRCT_TEST_NATIVE_DIRECT') != '1',
    reason='opt-in native GUI with private PipeWire and synthetic inputs',
)


def test_native_input_controls_and_independent_audio_stops(tmp_path):
    from tools.voice_acceptance import private_graph, wait_for, loopback, nodes, graph_snapshot, stop_process
    from tools.voice_b_poc import Producer, ToneCapture, tone, set_default
    from tools.source_bridge_acceptance import check_capture
    from models.audio_routing.pipewire_gate import PipeWireGate
    from models.audio_routing.source_bridge import select_source

    report = {'status': 'failed', 'cases': [], 'native_tauri': True, 'full_model_runtime': True,
              'real_vc_verified': False, 'real_inference': False, 'physical_input': False,
              'host_audio_changed': False, 'raw_pcm_saved': False,
              'timing_boundary': 'WebDriver operation call to first qualifying private-source read; 2s confirmation',
              'latency_percentiles': None}
    capture = None
    try:
        with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
            report['private_runtime_dir'] = os.environ['PIPEWIRE_RUNTIME_DIR']
            loopback(stack, 'vrct.control.decoy')
            decoy = Producer(stack, 'vrct.control.decoy.sink', 1760)
            set_default('source', 'vrct.control.decoy.source')
            input_process = loopback(stack, 'vrct.control.input')
            source_audio = Producer(stack, 'vrct.control.input.sink', 440)
            gate = PipeWireGate()
            capture = ToneCapture(stack, 'vrct.managed.source')
            # Fixed 880Hz PCM through the real HTTP client/scheduler/output.
            # Content length limits the fixture even if a stop regression occurs.
            pcm = tone(880) * 600
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    assert self.path == '/v1/audio/speech' and data['response_format'] == 'pcm'
                    self.send_response(200)
                    self.send_header('Content-Type', 'audio/pcm')
                    self.send_header('X-Sample-Rate', '48000')
                    self.send_header('Content-Length', str(len(pcm)))
                    self.end_headers()
                    try:
                        self.wfile.write(pcm)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = Thread(target=lambda: server.serve_forever(.05), daemon=True)
            thread.start()
            def close_server():
                server.shutdown()
                server.server_close()
                thread.join(2)
            stack.callback(close_server)
            state = initial_state(tmp_path)

            def observe(name, action=lambda: None, present=(), silent=False):
                before = capture.snapshot()
                started = time.monotonic_ns()
                action()
                first = wait_for(lambda: capture.settled(started, present=present,
                                 absent=tuple(f for f in (440, 880, 1760) if f not in present),
                                 silent=silent), timeout=6, code=name + '_not_observed')
                after = capture.snapshot()
                check_capture(before, after)
                assert after['detected_frames']['1760'] == 0
                report['cases'].append({'case': name, 'operation_to_read_ms': (first - started) / 1e6,
                    'confirmation_ms': (after['last_read_ns'] - first) / 1e6,
                    'present_hz': list(present), 'silent': silent})

            def selected_value():
                selected = select_source(graph_snapshot(), 'vrct.control.input.source')
                return json.dumps([str(selected.cookie), str(selected.serial), selected.name,
                                   selected.media_class], separators=(',', ':'))

            with NativeWebDriver(tmp_path / 'first', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                ui.wait("return [...document.querySelectorAll('label')].some(e => e.firstChild.textContent.trim() === 'Input to forward')")
                ui.select('Audio route', 'managed')
                ui.select('Read aloud', 'original')
                ui.fill('Japanese server (Irodori)', f'http://127.0.0.1:{server.server_port}')
                ui.click_text('button', 'Save voice settings')
                wait_for(lambda: json.loads((state / 'config.json').read_text()).get('VOICE_SETTINGS', {}).get('routing') == 'managed')
                wait_for(lambda: gate.inspect()['muted'])
                ui.select('Input to forward', selected_value())
                observe('selection_stays_silent', silent=True)
                observe('start_preserves_global_mute', lambda: ui.click_text('button', 'Start input forwarding'), silent=True)
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Input forwarding connected')")
                observe('resume_selected_input', lambda: ui.click_text('button', 'Resume voice'), present=(440,))

                def send_tts():
                    ui.click_text('p', 'Go Back')
                    field = ui.command('POST', '/element', {'using': 'css selector', 'value': 'textarea'})
                    ui.element_command(field, 'value', {'text': '入力と読み上げの独立停止テストです。'})
                    ui.click('[class*="message_send_button"]')
                observe('tts_coexists', send_tts, present=(440, 880))
                ui.open_voice_settings()
                observe('input_stop_keeps_tts', lambda: ui.click_text('button', 'Stop input forwarding'), present=(880,))
                # Navigating away loses the local UI selection; explicit reselect.
                ui.select('Input to forward', selected_value())
                observe('explicit_restart_with_tts', lambda: ui.click_text('button', 'Start input forwarding'), present=(440, 880))
                observe('tts_stop_keeps_input', lambda: ui.click_text('button', 'Stop playback and clear queue'), present=(440,))
                observe('whole_mute', lambda: ui.click_text('button', 'Mute until resumed'), silent=True)
                observe('whole_resume', lambda: ui.click_text('button', 'Resume voice'), present=(440,))
                observe('source_loss', lambda: stop_process(input_process), silent=True)
                source_audio.close()
                loopback(stack, 'vrct.control.input')
                replacement = Producer(stack, 'vrct.control.input.sink', 440)
                observe('same_name_no_reconnect', silent=True)
                ui.click_text('button', 'Refresh inputs')
                ui.wait("return [...document.querySelectorAll('select option:checked')].some(e => e.textContent === 'Disconnected')")
                ui.select('Input to forward', selected_value())
                observe('explicit_reselect_after_loss', lambda: ui.click_text('button', 'Start input forwarding'), present=(440,))
                def external():
                    ui.select('Read aloud', 'off')
                    ui.select('Audio route', 'external')
                    ui.click_text('button', 'Save voice settings')
                observe('external_routing_stops_input', external, silent=True)
                wait_for(lambda: json.loads((state / 'config.json').read_text())['VOICE_SETTINGS']['routing'] == 'external')
                ui.select('Audio route', 'managed')
                ui.click_text('button', 'Save voice settings')
                wait_for(lambda: json.loads((state / 'config.json').read_text())['VOICE_SETTINGS']['routing'] == 'managed')
                ui.wait("return [...document.querySelectorAll('button')].some(e => e.textContent === 'Start input forwarding' && !e.disabled)")
                ui.click_text('button', 'Start input forwarding')
                observe('input_before_exit', lambda: ui.click_text('button', 'Resume voice'), present=(440,))
                ui.assert_rendered()
                observe('app_exit_closes_input', ui.close_app, silent=True)
            assert not any(name.startswith('vrct.source-bridge.') for name in nodes())
            with NativeWebDriver(tmp_path / 'second', {'VRCT_CONFIG_DIR': str(state)}) as ui:
                ui.wait("return document.querySelector('textarea') !== null")
                ui.open_voice_settings()
                observe('app_restart_off', silent=True)
                ui.wait("return [...document.querySelectorAll('[role=status]')].some(e => e.textContent === 'Input forwarding stopped')")
                assert ui.evaluate('return arguments[0].value', ui.control('Input to forward')) == ''
                assert not any(name.startswith('vrct.source-bridge.') for name in nodes())
                ui.assert_rendered()
                ui.close_app()
            assert not decoy.failure and not replacement.failure
            report['capture'] = capture.snapshot()
        assert not Path(report['private_runtime_dir']).exists()
        report['private_graph_removed'] = True
        report['status'] = 'passed'
    finally:
        if capture and 'capture' not in report:
            report['capture'] = capture.snapshot()
        (tmp_path / 'native-direct-report.json').write_text(json.dumps(report, indent=2))
