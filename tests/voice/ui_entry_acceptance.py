"""Opt-in browser -> real stdio Main/Controller -> real PipeWire acceptance.

Requires npm dependencies, the voice-ui-test dependency group (tools/dev.py setup --scope browser), an existing
Chromium executable and native gate. Without --model a local PCM fixture is used.
This is not native Tauri/full Model runtime or VRChat acceptance.
"""
import argparse
import base64
from collections import Counter
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import math
import os
from pathlib import Path
from queue import Queue, Empty
import socket
import struct
import subprocess
import sys
from threading import Thread
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src-python')]
from tools.live_tts_acceptance import SpeechServer, SHORT, LONG, read_wav  # noqa: E402
from tools.voice_acceptance import private_graph, wait_for  # noqa: E402
from tools.voice_b_poc import ToneCapture, settled  # noqa: E402
from tools.vrchat_gui_probe import Capture  # noqa: E402
from tools.vrchat_audio_probe import compare_pcm  # noqa: E402
from tools.managed_vrchat_probe import require_continuous_capture  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate  # noqa: E402


class FixtureServer:
    def __init__(self):
        self.port = 0
        self.requests = []

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                body = b'{"status":"ok"}' if self.path == '/health' else b'{"data":[]}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path != '/v1/audio/speech' or data.get('response_format') != 'pcm':
                    self.send_error(400)
                    return
                owner.requests.append(data)
                duration = 12 if len(data['input']) > 80 else 3
                # Unequal envelope segments give the exactly-once detector a
                # distinctive reference. No physical microphone is captured.
                pcm = bytearray()
                for i in range(48000 * duration):
                    t = i / 48000
                    amp = (0, .5, .2, .8, .1, .6, .3)[int(t * 7) % 7]
                    pcm.extend(struct.pack('<h', round(12000 * amp * math.sin(2 * math.pi * 440 * t))))
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'audio/pcm')
                    self.send_header('X-Sample-Rate', '48000')
                    self.send_header('Content-Length', str(len(pcm)))
                    self.end_headers()
                    self.wfile.write(pcm)
                except (OSError, ConnectionError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
        self.port = self.server.server_port
        self.thread = Thread(target=lambda: self.server.serve_forever(.01), daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'

    def stop(self, kill=False):
        if hasattr(self, 'server'):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(2)
            del self.server


class Sidecar:
    def __init__(self, output, osc_port):
        self.output, self.responses, self.writes = output, Queue(), []
        self.stderr = (output / 'sidecar-stderr.log').open('w')
        self.raw = (output / 'sidecar-stdout.jsonl').open('w')
        self.process = subprocess.Popen([
            sys.executable, '-u', str(Path(__file__).with_name('entry_fixture.py')),
            '--output', str(output), '--osc-port', str(osc_port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True)
        self.thread = Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        for line in self.process.stdout:
            self.raw.write(line)
            self.raw.flush()
            self.responses.put(line)

    def write(self, line):
        self.writes.append({'time_ns': time.monotonic_ns(), 'wire': json.loads(line)})
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def drain(self):
        result = []
        while True:
            try:
                result.append(self.responses.get_nowait())
            except Empty:
                return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(3)
        self.thread.join(2)
        for stream in [self.process.stdin, self.process.stdout, self.stderr, self.raw]:
            stream.close()


def execute(args, report):
    from playwright.sync_api import sync_playwright
    from pythonosc.osc_packet import OscPacket

    with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf'), ExitStack() as stack:
        report['private_runtime_dir'] = os.environ['PIPEWIRE_RUNTIME_DIR']
        gate = PipeWireGate()
        report['initial_gate'] = gate.inspect()
        capture = ToneCapture(stack, 'vrct.managed.source')
        osc = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        osc.bind(('127.0.0.1', 0))
        osc.setblocking(False)
        backend_dir = args.output / 'backend'
        backend_dir.mkdir()
        sidecar = Sidecar(backend_dir, osc.getsockname()[1])
        stack.callback(sidecar.close)
        report['sidecar_pid'] = sidecar.process.pid
        server = SpeechServer(SimpleNamespace(model=args.model, output=args.output,
                    speech_binary=args.speech_binary, device='Vulkan0')) if args.model else FixtureServer()
        stack.callback(server.stop)
        server.start()
        report['server_runs'] = server.runs if args.model else []
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        vite_log = stack.enter_context((args.output / 'vite.log').open('w'))
        vite = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1',
                                 '--port', str(port), '--strictPort'], cwd=ROOT, stdout=vite_log, stderr=vite_log)

        def close_vite():
            vite.terminate()
            try:
                vite.wait(5)
            except subprocess.TimeoutExpired:
                vite.kill()
                vite.wait(3)
        stack.callback(close_vite)
        report['vite_pid'] = vite.pid
        wait_for(lambda: 'Local:' in (args.output / 'vite.log').read_text(), timeout=15, code='vite_not_ready')
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(executable_path=str(args.chromium), headless=True, args=['--disable-gpu'])
        stack.callback(browser.close)
        report['browser_version'] = browser.version
        page = browser.new_page(viewport={'width': 1200, 'height': 1200})
        page.set_default_timeout(8000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def write(line):
            if args.negative_control == 'drop-stop' and json.loads(line)['endpoint'] == '/run/stop_voice':
                return
            sidecar.write(line)
            if args.negative_control == 'duplicate-chat' and json.loads(line)['endpoint'] == '/run/send_message_box':
                sidecar.write(line)
        page.expose_function('sidecarWrite', write)
        page.expose_function('sidecarRead', sidecar.drain)
        page.goto(f'http://127.0.0.1:{port}/tests/voice/ui-entry/')
        report['cases'] = []

        def state():
            return page.evaluate('window.entry.state')

        def pause(seconds):
            page.wait_for_timeout(seconds * 1000)

        def until(expression, timeout=10000):
            page.wait_for_function(expression, timeout=timeout)

        def rpc(endpoint, data=None):
            count = page.evaluate('window.entry.received.length')
            page.evaluate('([endpoint,data]) => window.sidecarWrite(JSON.stringify({endpoint,data:btoa(unescape(encodeURIComponent(JSON.stringify(data))))})+"\\n")', [endpoint, data])
            page.wait_for_function('([n,ep]) => window.entry.received.slice(n).some(x=>x.endpoint===ep)', arg=[count, endpoint])
            return page.evaluate('([n,ep]) => window.entry.received.slice(n).find(x=>x.endpoint===ep)', [count, endpoint])

        def snapshot():
            response = rpc('/__test__/snapshot')
            assert response['status'] == 200, response
            return response['result']

        def services():
            path = backend_dir / 'services.jsonl'
            return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

        osc_messages = []

        def drain_osc():
            while True:
                try:
                    raw = osc.recv(65536)
                except BlockingIOError:
                    return
                for packet in OscPacket(raw).messages:
                    osc_messages.append({'address': packet.message.address, 'params': packet.message.params})

        def save_settings(mode='original'):
            page.get_by_label('Read aloud').select_option(mode)
            page.get_by_label('Audio route').select_option('managed')
            page.get_by_label('Japanese server (Irodori)', exact=True).fill(server.url)
            page.get_by_label('Translation slot').select_option('2')
            page.get_by_role('button', name='Save voice settings', exact=True).click()
            until(f'window.entry.state.settings?.mode === {json.dumps(mode)} && window.entry.state.settings.routing === "managed"')
            until('window.entry.state.route?.managed === true && window.entry.state.route.ready && !window.entry.state.route.pending')
            assert state()['error'] is None, state()

        def resume():
            until('window.entry.state.route?.managed === true && window.entry.state.route.ready && !window.entry.state.route.pending')
            if state()['route']['requested_muted']:
                page.get_by_role('button', name='Resume voice', exact=True).click()
            until('window.entry.state.route?.ready && !window.entry.state.route.pending && window.entry.state.route.observed_muted===false')

        def send(text):
            before = len(state()['logs'])
            page.locator('textarea').fill(text)
            begin = time.monotonic_ns()
            page.locator('[data-testid="chat"] button').click()
            until(f'window.entry.state.logs.length === {before + 1}')
            return begin, state()['logs'][-1]['id']

        def wire_time(endpoint, id=None):
            for item in reversed(sidecar.writes):
                wire = item['wire']
                if wire['endpoint'] == endpoint and (id is None or json.loads(base64.b64decode(wire['data']))['id'] == id):
                    return item['time_ns']
            raise AssertionError('expected_wire_write_missing')

        def delivered(id):
            until(f'window.entry.state.logs.some(x=>x.id==={json.dumps(id)} && x.status==="ok")')

        def done_case(case):
            assert not errors and not page.evaluate('window.entry.errors'), errors
            require_continuous_capture(capture.snapshot())
            assert gate.inspect()['identity'] == report['initial_gate']['identity']
            case['status'] = 'passed'
            report['cases'].append(case)
            print(json.dumps({'case': case['name'], 'status': 'passed'}), flush=True)

        def positive(name, translated=False):
            settled(capture, time.monotonic_ns(), 'before_positive_not_silent', silent=True)
            before = snapshot()
            drain_osc()
            osc_index = len(osc_messages)
            journal_index = len(services())
            recorded = Capture('vrct.managed.source', args.output / f'{name}.pcm')
            try:
                pause(.3)
                begin, id = send(SHORT)
                delivered(id)
                deadline = time.monotonic() + 15
                while True:
                    after = snapshot()
                    if after['voice']['completed'] == before['voice']['completed'] + 1:
                        break
                    assert time.monotonic() < deadline, 'speech_not_completed'
                    pause(.1)
                settled(capture, time.monotonic_ns(), 'after_positive_not_silent', silent=True)
            finally:
                observation = recorded.close()
            assert observation['valid'], observation
            records = after['pcm'][len(before['pcm']):]
            assert len(records) == 1 and records[0]['complete'], records
            audio = compare_pcm(read_wav(backend_dir / records[0]['wav']), (args.output / f'{name}.pcm').read_bytes(), 48000)
            assert audio['verdict'] == 'pass' and audio['occurrences'] == 1, audio
            drain_osc()
            messages = [m for m in osc_messages[osc_index:] if m['address'] == '/chatbox/input']
            expected_text = (SHORT + ' (Hello, translated fixture. / こんにちは。翻訳の接続テストです。)') if translated else SHORT
            assert messages == [{'address': '/chatbox/input', 'params': [expected_text, True, False]}], messages
            journal = services()[journal_index:]
            assert [x['text'] for x in journal if x['kind'] == 'history_contract'] == [SHORT], journal
            ws = [x['payload'] for x in journal if x['kind'] == 'websocket_contract']
            assert len(ws) == 1 and ws[0]['type'] == 'CHAT' and ws[0]['message'] == SHORT
            assert set(ws[0]) == {'type', 'src_languages', 'dst_languages', 'message', 'translation', 'transliteration'}
            assert ws[0]['translation'] == (['Hello, translated fixture.', 'こんにちは。翻訳の接続テストです。'] if translated else [])
            requests = [x['text'] for x in journal if x['kind'] == 'inference_request']
            assert requests == ['こんにちは。翻訳の接続テストです。' if translated else SHORT], requests
            with capture.lock:
                first = next(t for t, _, nonzero in capture.history if t >= begin and nonzero)
            wire_ns = wire_time('/run/send_message_box', id)
            done_case({'name': name, 'id': id, 'click_begin_ns': begin, 'source_first_read_ns': first,
                       'stdio_write_begin_ns': wire_ns, 'stdio_to_source_ms': (first - wire_ns) / 1e6,
                       'click_to_source_ms': (first - begin) / 1e6, 'audio': audio, 'capture': observation,
                       'osc': messages, 'websocket_contract': ws})

        try:
            until('window.entry?.state?.settings != null')
            save_settings()
            resume()
            positive('normal')
            # Further cases use the same real UI controls and wire receiver.
            for name, button in [('cancel', 'Stop playback and clear queue'), ('mute', 'Mute until resumed')]:
                before = snapshot()
                started, id = send(LONG)
                wait_for(lambda: any(t > started and nz for t, _, nz in capture.history), timeout=12, code='long_audio_missing')
                pause(.3)
                command = time.monotonic_ns()
                page.get_by_role('button', name=button, exact=True).click()
                first = settled(capture, command, 'stop_not_silent', silent=True)
                after = snapshot()
                assert after['voice']['cancelled'] == before['voice']['cancelled'] + 1, after
                # Browser dispatch/actionability overhead is included here;
                # retain values rather than claiming native Tauri latency.
                latency = (first - command) / 1e6
                assert latency <= 500, latency
                wire_ns = wire_time('/run/mute_voice' if name == 'mute' else '/run/stop_voice')
                wire_latency = (first - wire_ns) / 1e6
                assert 0 <= wire_latency <= 250, wire_latency
                done_case({'name': name, 'command_ns': command, 'first_silent_read_ns': first,
                           'click_to_silence_ms': latency, 'stdio_write_begin_ns': wire_ns,
                           'stdio_to_silence_ms': wire_latency})
            before = snapshot()
            started, id = send(SHORT)
            delivered(id)
            pause(2.2)
            after = snapshot()
            assert len(after['pcm']) == len(before['pcm'])
            assert not any(t > started and nz for t, _, nz in capture.history)
            done_case({'name': 'held-mute-rejects-new'})
            resume()
            save_settings('off')
            before = snapshot()
            started, id = send(SHORT)
            delivered(id)
            pause(2.2)
            assert len(snapshot()['pcm']) == len(before['pcm'])
            assert not any(t > started and nz for t, _, nz in capture.history)
            done_case({'name': 'off-keeps-text-silent'})
            save_settings()
            resume()
            positive('after-off')
            # Stop old queued intent while all ordinary workers are occupied.
            (backend_dir / 'release').unlink(missing_ok=True)
            blocked_before = len([x for x in services() if x['kind'] == 'blocked'])
            for i in range(3):
                page.evaluate('i=>window.sidecarWrite(JSON.stringify({endpoint:"/__test__/busy/"+i})+"\\n")', i)
            wait_for(lambda: len([x for x in services() if x['kind'] == 'blocked']) == blocked_before + 3,
                     timeout=3, code='workers_not_blocked')
            before = len(sidecar.writes)
            started, queued_id = send(SHORT)
            page.get_by_role('button', name='Stop playback and clear queue').click()
            until('window.entry.received.at(-1)?.endpoint === "/run/stop_voice"', timeout=2000)
            stop_response_ns = time.monotonic_ns()
            (backend_dir / 'release').touch()
            delivered(queued_id)
            pause(2.2)
            assert not any(t > started and nz for t, _, nz in capture.history)
            done_case({'name': 'busy-workers-stop-and-expire-queued', 'id': queued_id,
                       'begin_ns': started, 'stop_response_observed_ns': stop_response_ns,
                       'wire_endpoints': [x['wire']['endpoint'] for x in sidecar.writes[before:]]})
            positive('fresh-after-busy-stop')
            # Invalid settings must leave the working configuration intact and
            # return an error through the production UI response route.
            previous = state()['settings']
            page.get_by_label('Japanese server (Irodori)', exact=True).fill('https://invalid.example')
            page.get_by_role('button', name='Save voice settings', exact=True).click()
            until('window.entry.state.error === "VOICE_SETTINGS_INVALID"')
            assert state()['settings'] == previous
            done_case({'name': 'invalid-settings-preserve-working-config'})
            save_settings()
            resume()

            # Real Controller translation branch, controlled external translator.
            assert rpc('/__test__/translation', True)['status'] == 200
            for mode in ['original', 'translated']:
                save_settings(mode)
                resume()
                (backend_dir / 'release').unlink(missing_ok=True)
                before = snapshot()
                blocked_before = len([x for x in services() if x['kind'] == 'blocked'])
                started, id = send(LONG)
                wait_for(lambda: len([x for x in services() if x['kind'] == 'blocked']) > blocked_before,
                         timeout=3, code='translator_not_blocked')
                if mode == 'original':
                    wait_for(lambda: any(t > started and nz for t, _, nz in capture.history),
                             timeout=12, code='original_waited_for_translation')
                else:
                    pause(.6)
                    assert not any(t > started and nz for t, _, nz in capture.history)
                    assert len(snapshot()['pcm']) == len(before['pcm'])
                assert state()['logs'][-1]['status'] == 'pending'
                page.get_by_role('button', name='Stop playback and clear queue').click()
                stopped = time.monotonic_ns()
                settled(capture, stopped, 'translation_cancel_not_silent', silent=True)
                (backend_dir / 'release').touch()
                delivered(id)
                pause(2.2)
                after = snapshot()
                assert len(after['pcm']) == len(before['pcm']) + (mode == 'original')
                assert not any(t > stopped + 250_000_000 and nz for t, _, nz in capture.history)
                done_case({'name': mode + '-translation-wait-and-cancel', 'id': id})
            positive('translated-selected-slot', translated=True)
            assert rpc('/__test__/translation', False)['status'] == 200
            save_settings()
            resume()

            before = snapshot()
            started, id = send(LONG)
            wait_for(lambda: any(t > started and nz for t, _, nz in capture.history),
                     timeout=12, code='crash_test_audio_missing')
            pause(.3)
            command = time.monotonic_ns()
            server.stop(kill=True)
            first = settled(capture, command, 'server_failure_not_silent', silent=True)
            after = snapshot()
            assert after['voice']['errors'] == before['voice']['errors'] + 1
            assert after['voice']['last_error'] == 'server_unavailable', after
            latency = (first - command) / 1e6
            assert latency <= 250, latency
            until('window.entry.state.status.last_error === "server_unavailable"')
            assert page.get_by_role('alert').is_visible()
            done_case({'name': 'server-failure-visible-and-silent', 'command_ns': command,
                       'first_silent_read_ns': first, 'command_to_silence_ms': latency})
            before = snapshot()
            started, id = send(SHORT)
            delivered(id)
            pause(2.2)
            after = snapshot()
            assert after['voice']['errors'] == before['voice']['errors'] + 1
            assert after['voice']['last_error'] == 'transport_error'
            assert not any(t > started and nz for t, _, nz in capture.history)
            done_case({'name': 'server-unavailable-keeps-text-silent'})
            server.start()
            pause(2.2)
            assert not any(t > started and nz for t, _, nz in capture.history), 'stale_audio_replayed_on_reconnect'
            positive('fresh-after-server-restart')
            # Stops/mute/errors must preserve all legacy text delivery, including
            # delayed and queued messages, not just the normal-audio examples.
            drain_osc()
            sent = [json.loads(base64.b64decode(x['wire']['data'])) for x in sidecar.writes
                    if x['wire']['endpoint'] == '/run/send_message_box']
            history = [x['text'] for x in services() if x['kind'] == 'history_contract']
            ws = [x['payload'] for x in services() if x['kind'] == 'websocket_contract']
            chat_osc = [x for x in osc_messages if x['address'] == '/chatbox/input']
            logs = state()['logs']
            assert len(sent) == len(history) == len(ws) == len(chat_osc) == len(logs)
            assert Counter(x['message'] for x in sent) == Counter(history) == Counter(x['message'] for x in ws)
            assert {x['id'] for x in sent} == {x['id'] for x in logs}
            assert all(x['status'] == 'ok' for x in logs)
            done_case({'name': 'all-text-delivery-compatible', 'messages': len(sent),
                       'osc_packets': len(chat_osc), 'history_calls': len(history), 'websocket_calls': len(ws)})
            page.screenshot(path=str(args.output / 'ui-final.png'), full_page=True)
            report['final_state'] = state()
            report['final_capture'] = capture.snapshot()
            report['status'] = 'passed'
        finally:
            report['page_errors'] = errors
            report['wire'] = sidecar.writes
            report['ui_responses'] = page.evaluate('window.entry?.received || []')
            report['services'] = services()
            report['osc'] = osc_messages
            if report['status'] != 'passed':
                page.screenshot(path=str(args.output / 'ui-failed.png'), full_page=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--chromium', type=Path, required=True)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--speech-binary', default='speech')
    parser.add_argument('--negative-control', choices=['duplicate-chat', 'drop-stop'])
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failed', 'real_tts': bool(args.model), 'native_tauri': False,
              'full_model_runtime': False, 'vrchat': False, 'host_audio_changed': False,
              'negative_control': args.negative_control, 'cases': []}
    sources = ['tests/voice/ui_entry_acceptance.py', 'tests/voice/entry_fixture.py',
               'tests/voice/test_controller_integration.py', 'tests/voice/ui-entry/entry.jsx',
               'src-python/mainloop.py', 'src-python/controller.py',
               'src-python/models/tts/speechcpp_tts.py', 'src-python/models/tts/tts_scheduler.py',
               'src-python/models/audio_routing/managed_route.py', 'src-python/models/audio_routing/audio_router.py',
               'src-ui/logics/common/useStdoutToPython.js', 'src-ui/logics/common/useMessage.js',
               'src-ui/logics/useReceiveRoutes.js', 'src-ui/logics/voice/useVoice.js',
               'src-ui/views/app/main_page/main_section/message_container/message_input_box/MessageInputBox.jsx',
               'src-ui/views/app/config_page/setting_section/setting_box/advanced_settings/VoiceSettings.jsx']
    report['source_sha256'] = {s: hashlib.sha256((ROOT / s).read_bytes()).hexdigest() for s in sources}
    try:
        execute(args, report)
    except Exception as exc:
        import traceback
        report['failure'] = str(exc) or type(exc).__name__
        report['traceback'] = traceback.format_exc()
    backend_final = args.output / 'backend/backend-final.json'
    if backend_final.exists():
        report['backend_final'] = json.loads(backend_final.read_text())
    report['cleanup'] = {
        'owned_processes_exited': all(not Path(f'/proc/{pid}').exists() for pid in
            [report.get('sidecar_pid', -1), report.get('vite_pid', -1)] + [x['pid'] for x in report.get('server_runs', [])]),
        'private_runtime_removed': bool(report.get('private_runtime_dir')) and not Path(report['private_runtime_dir']).exists(),
        'route_and_bus_closed': all(report.get('backend_final', {}).get(k) is True for k in ['route_closed', 'bus_closed']),
    }
    if not all(report['cleanup'].values()):
        report.update(status='failed', cleanup_failure=True)
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'status': report['status'], 'failure': report.get('failure')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
