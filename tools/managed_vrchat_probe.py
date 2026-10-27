"""Prepared VRChat acceptance of the real managed voice control code.

No host setup/restart is performed by this tool. Inference is replaced with an
explicit WAV fixture; VoiceEventBus, VoiceRoute, durable state and native gate
are the application implementations. This is not a restart of the full GUI app.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src-python'))
from models.audio_routing.managed_route import VoiceRoute  # noqa: E402
from models.audio_routing.mute_state import MuteState  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, VC_SINK  # noqa: E402
from models.tts.settings import VoiceSettings  # noqa: E402
from models.tts.tts_scheduler import VoiceEventBus  # noqa: E402
from models.voice_events import AudioFrame, SpeechMessageEvent  # noqa: E402
from tools.voice_acceptance import wait_for  # noqa: E402
from tools.voice_b_poc import Producer, ToneCapture, settled, ready  # noqa: E402
from tools.vrchat_gui_probe import GUI, Capture, RATE, verify_route  # noqa: E402
from tools.vrchat_audio_probe import compare_pcm, silence_pcm  # noqa: E402


def require_checkpoint(expected, actual, status, stored):
    if (tuple(expected) != tuple(actual) or not status['ready'] or status['pending']
            or status['error'] is not None or status['observed_muted'] is not True
            or status['requested_muted'] is not True or stored is not True):
        raise RuntimeError('managed_mute_checkpoint_unconfirmed')
    return True


def require_continuous_capture(snapshot):
    if (snapshot['reader_error'] or snapshot['reader_eof']
            or snapshot['capture_gaps_over_100ms']):
        raise RuntimeError('capture_missing_or_stalled')


def worker(reference, state_file):
    with wave.open(str(reference), 'rb') as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
            raise ValueError('expected_48k_s16_mono_fixture')
        pcm = wav.readframes(wav.getnframes())

    class Fixture:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            for offset in range(0, len(pcm), 1920):
                token.check()
                yield AudioFrame(pcm[offset:offset + 1920], RATE)

    bus = VoiceEventBus(VoiceSettings(mode='original', routing='managed'), provider_factory=Fixture)
    route = VoiceRoute(bus, gate=PipeWireGate(), store=MuteState(state_file))

    def confirmed():
        return wait_for(lambda: route.status()['ready'] and not route.status()['pending'],
                        timeout=6, code='worker_not_confirmed')

    try:
        route.configure(True)
        confirmed()
        print(json.dumps({'started': True, 'pid': os.getpid()}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            action = request['action']
            reply = {}
            if action == 'shutdown':
                reply['closed_safely'] = route.close()
            elif action in ('mute', 'resume'):
                getattr(route, action)()
                confirmed()
            elif action == 'publish':
                reply['accepted'] = bus.publish(SpeechMessageEvent(
                    request['id'], 'chat', 'fixture', source_language='ja'))
            elif action != 'status':
                raise ValueError('unknown_action')
            reply.update(route=route.status(), bus=bus.status())
            print(json.dumps(reply), flush=True)
            if action == 'shutdown':
                break
    finally:
        route.close()
        bus.close()


class ControlProcess:
    def __init__(self, reference, state_file):
        self.process = subprocess.Popen([
            sys.executable, str(Path(__file__).resolve()), '--worker',
            '--reference', str(reference), '--state-file', str(state_file)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            self.started = self.receive()
        except Exception:
            self.close(force=True)
            raise

    def receive(self):
        if not self.selector.select(8):
            raise TimeoutError('control_reply_timeout')
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('control_process_exited')
        return json.loads(line)

    def request(self, action, **kwargs):
        self.process.stdin.write(json.dumps({'action': action, **kwargs}) + '\n')
        self.process.stdin.flush()
        return self.receive()

    def close(self, force=False):
        if self.process.poll() is None:
            if force:
                self.process.kill()
            else:
                try:
                    self.request('shutdown')
                finally:
                    self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.selector.close()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed:
                stream.close()


def gui_trial(gui, control, reference, output, replay_sink, *, muted=False):
    output.mkdir()
    gui.output = output
    captures = {}
    report = {'muted': muted}
    observation_start = len(gui.observations)
    try:
        gui.wait_state('ready', 6)
        for name, target in [('mic', SOURCE), ('replay', replay_sink)]:
            captures[name] = Capture(target, output / f'{name}.pcm', monitor=name == 'replay')
        started = time.monotonic()
        time.sleep(.5)
        gui.click(.715, .631)
        gui.wait_state('recording', 5)
        time.sleep(1.5)
        before = control.request('status')['bus']
        submitted = control.request('publish', id=output.name)
        report['publish_accepted'] = submitted['accepted']
        if submitted['accepted'] == muted:
            raise RuntimeError('incorrect_muted_publish_behavior')
        if not muted:
            wait_for(lambda: control.request('status')['bus']['completed'] == before['completed'] + 1,
                     timeout=15, code='fixture_not_completed')
        gui.wait_state('ready', 20)
        time.sleep(max(0, 24 - (time.monotonic() - started)))
        report['route'] = verify_route(SOURCE, replay_sink)
    except Exception as exc:
        report['failure'] = str(exc) or type(exc).__name__
        raise
    finally:
        report['captures'] = {key: capture.close() for key, capture in captures.items()}
        report['gui_observations'] = gui.observations[observation_start:]
        (output / 'result.json').write_text(json.dumps(report, indent=2))
    if not all(c['valid'] for c in report['captures'].values()):
        raise RuntimeError('gui_capture_missing_or_stalled')
    with wave.open(str(reference), 'rb') as wav:
        ref = wav.readframes(wav.getnframes())
    mic, replay = ((output / f'{key}.pcm').read_bytes() for key in ('mic', 'replay'))
    report['mic'] = silence_pcm(mic, RATE) if muted else compare_pcm(ref, mic, RATE)
    report['replay'] = compare_pcm(ref, replay, RATE)
    expected_count = 0 if muted else 1
    report['passed'] = report['mic']['verdict'] == 'pass' and report['replay'].get('occurrences') == expected_count
    (output / 'result.json').write_text(json.dumps(report, indent=2))
    if not report['passed']:
        raise RuntimeError('gui_recording_assertion_failed')
    return report


def run(args, report):
    store = MuteState(args.state_file)
    gate = PipeWireGate()
    initial = gate.inspect()
    if not initial['muted']:
        raise RuntimeError('expected_initial_native_mute')
    identity = initial['identity']
    report['initial'] = initial
    report['route_before'] = verify_route(SOURCE, args.replay_sink)
    gui = GUI(args.window, args.socket, args.output, args.ready_image, args.recording_image)
    report['gui_observations'] = gui.observations
    with ExitStack() as stack:
        control = ControlProcess(args.reference, args.state_file)
        stack.callback(control.close)
        report['control_pid_before'] = control.process.pid
        capture = ToneCapture(stack, SOURCE)
        settled(capture, time.monotonic_ns(), 'initial_not_silent', silent=True)
        require_checkpoint(identity, gate.inspect()['identity'], control.request('status')['route'], store.read())
        control.request('resume')
        report['single_replay'] = gui_trial(gui, control, args.reference, args.output / 'single', args.replay_sink)
        vc = Producer(stack, VC_SINK, 440)
        ready(capture, 440)
        report['engine_pid'] = vc.output.process.pid
        engine_exit_ns = time.monotonic_ns()
        vc.output.process.kill()
        vc.close()
        settled(capture, engine_exit_ns, 'engine_exit_not_silent', silent=True)
        if gate.inspect()['identity'] != identity:
            raise RuntimeError('engine_exit_replaced_endpoint')
        report['engine_exit'] = {'same_identity': True, 'capture': capture.snapshot(),
                                 'route': verify_route(SOURCE, args.replay_sink)}
        vc = Producer(stack, VC_SINK, 440)
        ready(capture, 440)
        start = time.monotonic_ns()
        control.request('mute')
        first = settled(capture, start, 'mute_not_silent', silent=True)
        state = control.request('status')['route']
        require_checkpoint(identity, gate.inspect()['identity'], state, store.read())
        report['mute'] = {'command_ns': start, 'first_silent_frame_ns': first,
                          'command_to_first_silent_read_ms': (first - start) / 1e6,
                          'confirmed_ns': capture.snapshot()['last_read_ns'], 'route_state': state,
                          'external_producer_still_running': vc.output.process.poll() is None}
        if not report['mute']['external_producer_still_running'] or vc.failure:
            raise RuntimeError('external_producer_died_before_mute_check')
        held = capture.snapshot()['nonzero_frames']
        held_before = capture.snapshot()
        control.close(force=True)
        report['stored_after_sigkill'] = store.read()
        settled(capture, time.monotonic_ns(), 'control_exit_not_silent', silent=True)
        control = ControlProcess(args.reference, args.state_file)
        stack.callback(control.close)
        report['control_pid_after'] = control.process.pid
        report['voice_control_process_restarted'] = True
        state = control.request('status')['route']
        require_checkpoint(identity, gate.inspect()['identity'], state, store.read())
        settled(capture, time.monotonic_ns(), 'restart_not_silent', silent=True)
        if capture.snapshot()['nonzero_frames'] != held:
            raise RuntimeError('restart_leaked_audio')
        report['control_restart'] = {'route_state': state, 'same_identity': True,
                                     'route': verify_route(SOURCE, args.replay_sink)}
        report['muted_replay'] = gui_trial(gui, control, args.reference, args.output / 'muted',
                                           args.replay_sink, muted=True)
        if vc.output.process.poll() is not None or vc.failure or capture.snapshot()['nonzero_frames'] != held:
            raise RuntimeError('muted_hold_unverified')
        held_after = capture.snapshot()
        report['muted_hold'] = {'before': held_before, 'after': held_after,
                               'external_producer_still_running': True,
                               'observed_frames': held_after['frames'] - held_before['frames'],
                               'additional_nonzero_frames': held_after['nonzero_frames'] - held}
        control.request('resume')
        ready(capture, 440)
        report['explicit_resume_restores_external_signal'] = True
        control.request('mute')
        settled(capture, time.monotonic_ns(), 'final_mute_missing', silent=True)
        report['final_capture'] = capture.snapshot()
        require_continuous_capture(report['final_capture'])
        report['route_after'] = verify_route(SOURCE, args.replay_sink)
        if report['route_after'] != report['route_before']:
            raise RuntimeError('vrchat_route_changed')
        report['gui_observations'] = gui.observations
    report['status'] = 'passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    for name in ('reference', 'state-file'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('window', 'socket', 'replay-sink'):
        parser.add_argument('--' + name)
    for name in ('ready-image', 'recording-image', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.reference, args.state_file)
        return 0
    if not all((args.window, args.socket, args.replay_sink, args.ready_image, args.recording_image, args.output)):
        parser.error('GUI/route/output arguments required')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failed', 'boundary': 'managed virtual source + local VRChat test playback',
              'full_vrct_gui_restarted': False, 'voice_control_process_restarted': False,
              'real_vc_model': False, 'inference': 'WAV fixture through real VoiceEventBus',
              'noise_suppression': 'off', 'physical_headphone_tested': False}
    try:
        run(args, report)
        report['voice_control_process_restarted'] = True
    except (Exception, KeyboardInterrupt) as exc:
        report['status'] = 'failed'
        report['failure'] = str(exc) or type(exc).__name__
    finally:
        (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'status': report['status'], 'failure': report.get('failure')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
