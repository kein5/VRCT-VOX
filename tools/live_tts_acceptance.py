"""Live speech.cpp acceptance on a private graph or prepared VRChat desktop UI.

Starts only the supplied local model/binary on localhost. Does not install host
routes, launch VRChat or prepare its GUI. Captures synthetic TTS audio, not a
physical microphone. Full VRCT GUI and remote-player latency are outside scope.
"""
import argparse
from contextlib import ExitStack, contextmanager, nullcontext
import http.client
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src-python'))
from models.audio_routing.managed_route import VoiceRoute  # noqa: E402
from models.audio_routing.mute_state import MuteState  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE  # noqa: E402
from models.tts.settings import VoiceSettings  # noqa: E402
from models.tts.speechcpp_tts import SpeechCppTTS, SpeechError  # noqa: E402
from models.tts.tts_scheduler import VoiceEventBus  # noqa: E402
from models.voice_events import SpeechMessageEvent  # noqa: E402
from tools.managed_vrchat_probe import require_checkpoint, require_continuous_capture  # noqa: E402
from tools.voice_acceptance import TimedRouter, idle, private_graph, wait_for  # noqa: E402
from tools.voice_b_poc import ToneCapture, settled  # noqa: E402
from tools.voice_route_acceptance import confirmed  # noqa: E402
from tools.vrchat_gui_probe import GUI, Capture, RATE, verify_route  # noqa: E402
from tools.vrchat_audio_probe import compare_pcm, silence_pcm  # noqa: E402

SHORT = 'こんにちは。音声の接続テストです。'
LONG = ('これは音声を途中で止めるための接続試験です。マイクの出力と停止後の無音を確認しています。' * 5)


def first_signal(history, since_ns):
    return next((stamp for stamp, _frequencies, nonzero in history if stamp >= since_ns and nonzero), None)


def require_outcome(before, after, expected):
    if after['active'] or after['queued'] or any(
            after[key] - before[key] != int(key == expected) for key in ('completed', 'cancelled', 'errors')):
        raise RuntimeError('request_outcome_unconfirmed')


class PCMTap:
    """Observe the actual HTTP provider. Keep disk I/O out of first-audio timing."""
    def __init__(self, output):
        self.output = output
        self.records = []  # One bus worker; inspect completed records only after idle.

    def provider(self, url):
        tap = self

        class Provider:
            def synthesize_stream(self, text, voice, language, token):
                record = {'started_ns': time.monotonic_ns(), 'first_pcm_ns': None, 'received_bytes': 0,
                          'complete': False, 'error': None, 'wav': f'generated-{len(tap.records):03d}.wav'}
                tap.records.append(record)
                pcm = bytearray()
                rate = None
                stream = SpeechCppTTS(url).synthesize_stream(text, voice, language, token)
                try:
                    for frame in stream:
                        if frame.sample_rate != RATE or frame.channels != 1:
                            raise ValueError('acceptance_requires_48k_mono')
                        rate = frame.sample_rate
                        if record['first_pcm_ns'] is None:
                            record['first_pcm_ns'] = time.monotonic_ns()
                        pcm.extend(frame.pcm)
                        record['received_bytes'] = len(pcm)
                        yield frame
                    record['complete'] = True
                except Exception as exc:
                    record['error'] = str(exc) if isinstance(exc, SpeechError) else type(exc).__name__
                    raise
                finally:
                    stream.close()
                    record.update(finished_ns=time.monotonic_ns(), samples=len(pcm) // 2, sample_rate=rate)
                    if rate:
                        with wave.open(str(tap.output / record['wav']), 'wb') as wav:
                            wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                            wav.writeframes(pcm)
        return Provider()


class SpeechServer:
    def __init__(self, args):
        self.args, self.process, self.log = args, None, None
        self.port, self.runs = 0, []

    def start(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('test_server_already_running')
        path = self.args.output / f'server-{len(self.runs):02d}.log'
        self.log = path.open('wb')
        self.process = subprocess.Popen([
            self.args.speech_binary, 'serve', str(self.args.model), '--host', '127.0.0.1',
            '--port', str(self.port), '--device', self.args.device], stdout=self.log, stderr=self.log)
        self.runs.append({'pid': self.process.pid, 'log': path.name, 'warmup_enabled': True})

        def ready():
            if self.process.poll() is not None:
                raise RuntimeError('speech_server_exited_during_start')
            match = re.search(r'Ready at http://127\.0\.0\.1:(\d+)/', path.read_text(errors='replace'))
            if not match:
                return False
            self.port = int(match[1])
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=1)
            try:
                conn.request('GET', '/health')
                response = conn.getresponse()
                response.read()
                return response.status == 200
            except OSError:
                return False
            finally:
                conn.close()
        wait_for(ready, timeout=45, code='speech_server_not_ready')
        self.runs[-1].update(port=self.port, ready=True)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'

    def stop(self, kill=False):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill() if kill else self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.runs[-1]['exit_code'] = self.process.returncode
        if self.log is not None:
            self.log.close()


@contextmanager
def captures(output, replay_sink=None):
    instances, result = {}, {}
    try:
        for key, target in [('mic', SOURCE)] + ([('replay', replay_sink)] if replay_sink else []):
            instances[key] = Capture(target, output / f'{key}.pcm', monitor=key == 'replay')
        yield result
    finally:
        result.update({key: value.close() for key, value in instances.items()})


def read_wav(path):
    with wave.open(str(path), 'rb') as wav:
        return wav.readframes(wav.getnframes())


class Session:
    def __init__(self, args, report, stack):
        self.args, self.report = args, report
        self.gate = PipeWireGate()
        initial = self.gate.inspect()
        if initial['muted'] is not True:
            raise RuntimeError('expected_initial_native_mute')
        self.identity = initial['identity']
        report['initial_gate'] = initial
        self.server = SpeechServer(args)
        stack.callback(self.server.stop)
        report['server_runs'] = self.server.runs
        self.server.start()
        self.tap = PCMTap(args.output)
        report['http_pcm_records'] = self.tap.records
        self.router = TimedRouter()
        self.bus = VoiceEventBus(VoiceSettings(mode='original', routing='managed', japanese_url=self.server.url),
                                 provider_factory=self.tap.provider, router=self.router)
        stack.callback(self.close_bus)
        self.store = MuteState(args.output / 'voice-state.json')
        self.route = VoiceRoute(self.bus, gate=self.gate, store=self.store)
        stack.callback(self.close_route)
        self.route.configure(True)
        confirmed(self.route)
        self.capture = ToneCapture(stack, SOURCE)
        settled(self.capture, time.monotonic_ns(), 'initial_not_silent', silent=True)
        self.gui = None
        if not args.private:
            report['route_before'] = verify_route(SOURCE, args.replay_sink)
            self.gui = GUI(args.window, args.socket, args.output, args.ready_image, args.recording_image)
        self.checkpoint()
        self.route.resume()
        confirmed(self.route)

    def close_bus(self):
        if not self.bus.close():
            raise RuntimeError('bus_shutdown_unconfirmed')

    def close_route(self):
        if not self.route.close():
            raise RuntimeError('route_shutdown_unconfirmed')

    def checkpoint(self):
        require_checkpoint(self.identity, self.gate.inspect()['identity'], self.route.status(), self.store.read())

    def signal(self, event):
        with self.capture.lock:
            return first_signal(self.capture.history, event.timestamp_ns)

    def publish(self, name, text):
        event = SpeechMessageEvent(name, 'chat', text, source_language='ja')
        if not self.bus.publish(event):
            raise RuntimeError('unexpected_publish_rejection')
        return event

    def new_case(self, name):
        case = {'name': name, 'status': 'running'}
        self.report['cases'].append(case)
        return case

    def finish(self, case, status='passed'):
        if self.gate.inspect()['identity'] != self.identity:
            raise RuntimeError('endpoint_identity_changed')
        if self.gui:
            case['vrchat_route'] = verify_route(SOURCE, self.args.replay_sink)
            if case['vrchat_route'] != self.report['route_before']:
                raise RuntimeError('vrchat_route_changed')
        require_continuous_capture(self.capture.snapshot())
        case['status'] = status
        print(json.dumps({'case': case['name'], 'status': case['status']}), flush=True)

    def prepare_gui(self, output):
        if self.gui:
            self.gui.output = output
            self.gui.wait_state('ready', 6)

    def record_gui(self):
        if self.gui:
            self.gui.click(.715, .631)
            self.gui.wait_state('recording', 5)
            time.sleep(1.5)

    def finish_gui(self, started):
        if self.gui:
            self.gui.wait_state('ready', 20)
            time.sleep(max(0, 24 - (time.monotonic() - started)))

    def positive(self, name):
        case = self.new_case(name)
        output = self.args.output / name
        output.mkdir()
        settled(self.capture, time.monotonic_ns(), 'pre_request_not_silent', silent=True)
        self.prepare_gui(output)
        before, index = self.bus.status(), len(self.tap.records)
        with captures(output, self.args.replay_sink if self.gui else None) as captured:
            started = time.monotonic()
            time.sleep(.5)
            self.record_gui()
            event = self.publish(name, SHORT)
            first = wait_for(lambda: self.signal(event), timeout=12, code='first_mic_audio_missing')
            after = wait_for(lambda: idle(self.bus), timeout=18, code='live_tts_did_not_finish')
            require_outcome(before, after, 'completed')
            settled(self.capture, time.monotonic_ns(), 'completion_not_silent', silent=True)
            self.finish_gui(started)
        case['captures'] = captured
        if not all(c['valid'] for c in captured.values()):
            raise RuntimeError('capture_missing_or_stalled')
        record = self.tap.records[index]
        if not record['complete']:
            raise RuntimeError('http_stream_incomplete')
        ref = read_wav(self.args.output / record['wav'])
        case['audio'] = {key: compare_pcm(ref, (output / f'{key}.pcm').read_bytes(), RATE) for key in captured}
        if any(value['verdict'] != 'pass' for value in case['audio'].values()):
            raise RuntimeError('live_audio_not_exactly_once')
        case['timing'] = {'event_ns': event.timestamp_ns, 'first_http_pcm_ns': record['first_pcm_ns'],
                          'first_write_ns': self.router.first_write_ns, 'first_source_read_ns': first}
        case['milliseconds'] = {key: (value - event.timestamp_ns) / 1e6 for key, value in case['timing'].items()
                                if key != 'event_ns'}
        case['bus_after'] = after
        self.reference = ref
        self.finish(case)

    def begin_long(self, name):
        settled(self.capture, time.monotonic_ns(), 'pre_fault_not_silent', silent=True)
        before = self.bus.status()
        event = self.publish(name, LONG)
        first = wait_for(lambda: self.signal(event), timeout=12, code='fault_test_audio_missing')

        def speaking():
            with self.capture.lock:
                history = list(self.capture.history)
            now = time.monotonic_ns()
            return (now - first > 300_000_000 and any(stamp > now - 60_000_000 and nonzero
                    for stamp, _, nonzero in history) and self.bus.status()['active'])
        wait_for(speaking, timeout=3, code='not_speaking_at_fault')
        return before, event

    def stop_or_mute(self, mute=False):
        case = self.new_case('held-mute' if mute else 'cancel')
        before, event = self.begin_long(case['name'])
        started = time.monotonic_ns()
        self.route.mute() if mute else self.bus.cancel()
        after = wait_for(lambda: idle(self.bus), timeout=8, code='cancel_not_idle')
        require_outcome(before, after, 'cancelled')
        first = settled(self.capture, started, 'cancel_not_silent', silent=True)
        case.update(event_ns=event.timestamp_ns, command_ns=started, first_silent_read_ns=first,
                    command_to_silence_ms=(first - started) / 1e6, bus_after=after)
        held = self.capture.snapshot()
        if mute:
            confirmed(self.route)
            self.checkpoint()
            record_count = len(self.tap.records)
            rejected = SpeechMessageEvent('muted-new', 'chat', SHORT, source_language='ja')
            if self.bus.publish(rejected):
                raise RuntimeError('muted_tts_accepted')
            output = self.args.output / 'muted-recording'
            output.mkdir()
            self.prepare_gui(output)
            with captures(output, self.args.replay_sink if self.gui else None) as captured:
                gui_started = time.monotonic()
                time.sleep(.5)
                self.record_gui()
                settled(self.capture, time.monotonic_ns(), 'mute_hold_not_silent', silent=True)
                self.finish_gui(gui_started)
            case['captures'] = captured
            if not all(c['valid'] for c in captured.values()):
                raise RuntimeError('muted_capture_missing')
            case['microphone'] = silence_pcm((output / 'mic.pcm').read_bytes(), RATE)
            if case['microphone']['verdict'] != 'pass' or len(self.tap.records) != record_count:
                raise RuntimeError('mute_did_not_block_audio_or_inference')
            if self.gui:
                case['replay'] = compare_pcm(self.reference, (output / 'replay.pcm').read_bytes(), RATE)
                if case['replay'].get('occurrences') != 0:
                    raise RuntimeError('muted_replay_detected_or_missing')
            self.checkpoint()
        else:
            settled(self.capture, time.monotonic_ns(), 'cancel_silence_not_held', silent=True)
            if self.gate.inspect()['muted']:
                raise RuntimeError('tts_cancel_changed_native_gate')
        current = self.capture.snapshot()
        if current['nonzero_frames'] != held['nonzero_frames']:
            raise RuntimeError('audio_returned_after_stop')
        case['silent_hold_frames'] = current['frames'] - held['frames']
        self.finish(case)

    def crash_server(self):
        case = self.new_case('server-crash')
        self.route.resume()
        confirmed(self.route)
        before, event = self.begin_long(case['name'])
        started = time.monotonic_ns()
        case['http_bytes_at_kill'] = self.tap.records[-1]['received_bytes']
        self.server.stop(kill=True)
        # Capture the localhost receive queue after the owned server has exited.
        case['tcp_after_kill'] = subprocess.check_output([
            'ss', '-tn', f'sport = :{self.server.port} or dport = :{self.server.port}'], text=True)
        case['initial_idle_window_seconds'] = 12
        try:
            after = wait_for(lambda: idle(self.bus), timeout=12, code='crashed_inference_not_idle')
            case['within_initial_idle_window'] = True
        except TimeoutError:
            case['within_initial_idle_window'] = False
            case['after_12_seconds'] = {'bus': self.bus.status(), 'capture': self.capture.snapshot(),
                                        'http_bytes': self.tap.records[-1]['received_bytes']}
            # Diagnostic continuation, not a relaxed pass threshold. Finish the
            # remaining scenarios while preserving the original failure.
            after = wait_for(lambda: idle(self.bus), timeout=23, code='crashed_inference_still_not_idle')
        case['idle_observed_ns'] = time.monotonic_ns()
        require_outcome(before, after, 'errors')
        if after['last_error'] not in ('transport_error', 'truncated_http', 'request_timeout'):
            raise RuntimeError('unexpected_crash_error')
        first = settled(self.capture, started, 'server_crash_not_silent', silent=True)
        case.update(event_ns=event.timestamp_ns, killed_pid=self.server.process.pid, command_ns=started,
                    first_silent_read_ns=first, command_to_silence_ms=(first - started) / 1e6, bus_after=after)
        held = self.capture.snapshot()['nonzero_frames']
        before = self.bus.status()
        self.publish('server-unavailable', SHORT)
        after = wait_for(lambda: idle(self.bus), timeout=5, code='unavailable_request_not_idle')
        require_outcome(before, after, 'errors')
        settled(self.capture, time.monotonic_ns(), 'unavailable_server_not_silent', silent=True)
        if self.capture.snapshot()['nonzero_frames'] != held:
            raise RuntimeError('unavailable_server_produced_audio')
        case['unavailable_error'] = after['last_error']
        self.finish(case, 'passed' if case['within_initial_idle_window'] else 'failed')
        self.server.start()
        self.positive('recovery')


def run(args, report):
    graph = private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf') if args.private else nullcontext()
    with graph, ExitStack() as stack:
        session = Session(args, report, stack)
        for index in range(args.samples):
            session.positive(f'positive-{index + 1}')
        session.stop_or_mute()
        session.stop_or_mute(mute=True)
        session.crash_server()
        session.route.mute()
        confirmed(session.route)
        settled(session.capture, time.monotonic_ns(), 'final_mute_missing', silent=True)
        session.checkpoint()
        report['final_capture'] = session.capture.snapshot()
        require_continuous_capture(report['final_capture'])
        if session.gui:
            report['gui_observations'] = session.gui.observations
    report['status'] = 'passed' if all(c['status'] == 'passed' for c in report['cases']) else 'failed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--speech-binary', default='speech')
    parser.add_argument('--device', default='Vulkan0')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--private', action='store_true')
    for key in ('window', 'socket', 'replay-sink'):
        parser.add_argument('--' + key)
    for key in ('ready-image', 'recording-image'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if not args.model.is_file() or not 1 <= args.samples <= 30:
        parser.error('existing local model and 1..30 samples required')
    if not args.private and not all((args.window, args.socket, args.replay_sink, args.ready_image, args.recording_image)):
        parser.error('prepared GUI arguments required unless --private')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failed', 'cases': [], 'real_tts': True, 'real_vc': False,
              'full_vrct_gui_tested': False, 'physical_headphone_tested': False,
              'environment': 'private_pipewire' if args.private else 'host_pipewire_vrchat_desktop',
              'noise_suppression': None if args.private else 'off',
              'measurement_boundary': 'event creation to source 20ms read frame with peak >64/32768',
              'server_warmup_enabled': True}
    try:
        run(args, report)
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status='failed', failure=str(exc) or type(exc).__name__)
    finally:
        (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'status': report['status'], 'failure': report.get('failure')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
