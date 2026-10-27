"""Model-free B spike on a private PipeWire graph, with synthetic PCM only.

440 Hz = VC substitute, 880 Hz = TTS substitute, 1760 Hz = forbidden fallback.
The reported boundary is command start -> first qualifying 20 ms capture frame,
confirmed by two seconds of continued capture. This is not UI/VRChat latency.
"""
import argparse
from collections import deque
from contextlib import ExitStack
import csv
import json
import math
from pathlib import Path
import platform
import struct
import subprocess
import sys
from threading import Lock, Thread
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.voice_acceptance import (  # noqa: E402
    AudioFrame, VoiceEventBus, VoiceSettings, graph_snapshot, idle, loopback, make_event, nodes,
    private_graph, start_process, stop_process, wait_for,
)
from tools.voice_latency import summarize  # noqa: E402
from models.tts.speechcpp_tts import CancelToken  # noqa: E402

RATE = 48000
FRAME = 960  # 20 ms; observer timestamps are read completion, not ADC time.
FREQUENCIES = (440, 880, 1760)
WINDOW = tuple(0.5 - 0.5 * math.cos(2 * math.pi * n / (FRAME - 1)) for n in range(FRAME))
BASIS = {f: (tuple(w * math.cos(2 * math.pi * f * n / RATE) for n, w in enumerate(WINDOW)),
             tuple(w * math.sin(2 * math.pi * f * n / RATE) for n, w in enumerate(WINDOW)))
         for f in FREQUENCIES}


def tone(frequency):
    # 100 ms is an integral number of cycles for all three frequencies.
    return struct.pack('<4800h', *(round(2048 * math.sin(2 * math.pi * frequency * n / RATE))
                                  for n in range(4800)))


class ToneObservation:
    def __init__(self):
        self.lock = Lock()
        self.pending = bytearray()
        self.history = deque(maxlen=1000)
        self.counts = {f: 0 for f in FREQUENCIES}
        self.frames = self.sample_count = self.gaps = self.nonzero_frames = 0
        self.last_read_ns = None
        self.max_gap_ms = 0.0

    def feed(self, pcm, timestamp_ns):
        with self.lock:
            self.pending.extend(pcm)
            while len(self.pending) >= FRAME * 2:
                samples = struct.unpack('<960h', self.pending[:FRAME * 2])
                del self.pending[:FRAME * 2]
                found = set()
                for f, (cosines, sines) in BASIS.items():
                    real = sum(s * c for s, c in zip(samples, cosines))
                    imag = sum(s * c for s, c in zip(samples, sines))
                    if 2 * math.hypot(real, imag) / sum(WINDOW) > 400:
                        found.add(f)
                        self.counts[f] += 1
                nonzero = max(map(abs, samples)) > 64
                if self.last_read_ns is not None:
                    gap = (timestamp_ns - self.last_read_ns) / 1e6
                    self.max_gap_ms = max(self.max_gap_ms, gap)
                    if gap > 100:
                        self.gaps += 1
                self.frames += 1
                self.sample_count += FRAME
                self.nonzero_frames += nonzero
                self.last_read_ns = timestamp_ns
                self.history.append((timestamp_ns, found, nonzero))

    def snapshot(self):
        with self.lock:
            return {'frames': self.frames, 'sample_count': self.sample_count,
                    'last_read_ns': self.last_read_ns, 'capture_gaps_over_100ms': self.gaps,
                    'max_read_gap_ms': self.max_gap_ms, 'nonzero_frames': self.nonzero_frames,
                    'detected_frames': {str(f): n for f, n in self.counts.items()}}

    def settled(self, since_ns, *, absent=(), present=(), silent=False, duration_ms=2000, now_ns=None):
        now_ns = time.monotonic_ns() if now_ns is None else now_ns
        with self.lock:
            if not self.history or now_ns - self.history[-1][0] > 200_000_000:
                return None
            end = previous = self.history[-1][0]
            start = None
            for timestamp, found, nonzero in reversed(self.history):
                if (timestamp < since_ns or previous - timestamp > 100_000_000
                        or set(absent) & found or not set(present) <= found or (silent and nonzero)):
                    break
                start = previous = timestamp
            if start is not None and end - start >= duration_ms * 1e6:
                return start
        return None


class ToneCapture(ToneObservation):
    def __init__(self, stack, target, *, strict=True):
        super().__init__()
        self.reader_eof = False
        self.reader_error = None
        command = ['pw-cat', '--record', '--raw', '--format', 's16', '--rate', str(RATE),
                   '--channels', '1', '--latency', '10ms', '--target', target]
        if strict:
            command += ['--properties', '{ node.dont-fallback=true node.dont-reconnect=true }']
        self.process = start_process(stack, command + ['-'], stdout=subprocess.PIPE)
        self.thread = Thread(target=self.read, daemon=True)
        self.thread.start()
        stack.callback(self.close)
        wait_for(lambda: self.snapshot()['frames'], code='capture_not_ready')

    def read(self):
        try:
            while pcm := self.process.stdout.read1(FRAME * 2):
                self.feed(pcm, time.monotonic_ns())
            self.reader_eof = True
        except Exception as exc:
            self.reader_error = type(exc).__name__

    def snapshot(self):
        return {**super().snapshot(), 'reader_eof': self.reader_eof,
                'reader_error': self.reader_error}

    def close(self):
        stop_process(self.process)
        self.thread.join(2)
        self.process.stdout.close()


class Producer:
    """A separate pw-cat process in place of a VC engine; never captures input."""
    def __init__(self, stack, device, frequency):
        from models.audio_routing.devices_pipewire import PipeWireOutput
        self.token = CancelToken()
        self.output = PipeWireOutput(device, RATE, 1)
        self.failure = None
        self.pcm = tone(frequency)
        self.thread = Thread(target=self.run, daemon=True)
        self.thread.start()
        stack.callback(self.close)

    def run(self):
        try:
            while not self.token.is_set():
                self.output.write(self.pcm, self.token)
        except Exception as exc:
            if not self.token.is_set():
                self.failure = type(exc).__name__
        finally:
            self.output.close(drain=False, token=self.token)

    def close(self):
        self.token.cancel()
        self.thread.join(3)
        if self.thread.is_alive():
            raise RuntimeError('producer_did_not_stop')


class SyntheticTTS:
    def __init__(self, url):
        pass

    def synthesize_stream(self, text, voice, language, token):
        pcm = tone(880)
        while not token.is_set():
            token.check()
            yield AudioFrame(pcm, RATE)


def route(stack, name):
    start_process(stack, [
        'pw-loopback', '--name', name, '--channels', '1', '--channel-map', 'MONO',
        '--capture-props', f'media.class=Audio/Sink node.name={name}.sink node.virtual=true',
        '--playback-props', f'node.name={name}.output target.object=vrct.b.final.sink '
                            'node.dont-fallback=true node.dont-reconnect=true',
    ], stdout=subprocess.DEVNULL)
    wait_for(lambda: f'{name}.sink' in nodes())


def mute(name, value):
    node = nodes()[name]
    subprocess.run(['wpctl', 'set-mute', str(node['id']), '1' if value else '0'],
                   check=True, capture_output=True, timeout=3)


def set_default(kind, name):
    subprocess.run(['pw-metadata', '-n', 'default', '0', f'default.configured.audio.{kind}',
                    json.dumps({'name': name}), 'Spa:String:JSON'],
                   check=True, capture_output=True, timeout=3)
    def configured():
        return any(entry['key'] == f'default.audio.{kind}' and entry['value'].get('name') == name
                   for obj in graph_snapshot() if obj.get('props', {}).get('metadata.name') == 'default'
                   for entry in obj.get('metadata', []))
    wait_for(configured, code='decoy_not_default')


def settled(capture, start, code, **kwargs):
    return wait_for(lambda: capture.settled(start, **kwargs), timeout=6, code=code)


def measure(report, capture, metric, action, **kwargs):
    start = time.monotonic_ns()
    action()
    end = settled(capture, start, metric + '_not_settled', **kwargs)
    report['rows'].append({'metric': metric, 'environment': 'linux_private_pipewire_synthetic',
                           'warm': 'yes', 'start_ns': start, 'end_ns': end})
    return {'command_ns': start, 'first_qualifying_frame_ns': end,
            'confirmation_ns': capture.snapshot()['last_read_ns']}


def new_bus(stack):
    bus = VoiceEventBus(VoiceSettings(mode='original', output_device='vrct.b.tts.sink'),
                        provider_factory=SyntheticTTS, request_timeout=7200)
    stack.callback(bus.close)
    return bus


def ready(capture, *frequencies):
    settled(capture, time.monotonic_ns(), 'signals_not_ready', present=frequencies, duration_ms=100)


def confirm_mute_hold(capture, since_ns, before_nonzero):
    settled(capture, since_ns, 'mute_reopened_on_new_producer', silent=True)
    if capture.snapshot()['nonzero_frames'] != before_nonzero:
        raise RuntimeError('mute_hold_leaked_audio')


def consumer_observation(before, after, exit_code, fault_ns, now_ns):
    """A known disconnection differs from a live reader; stalls are missing data."""
    if (after.get('reader_error') or
            after['capture_gaps_over_100ms'] != before['capture_gaps_over_100ms']):
        return 'missing'
    if exit_code is not None and after.get('reader_eof'):
        return 'disconnected'
    last = after['last_read_ns'] or 0
    if (exit_code is None and not after.get('reader_eof') and
            after['frames'] > before['frames'] and last >= fault_ns + 2_000_000_000 and
            now_ns - last <= 200_000_000):
        return 'live'
    return 'missing'


def validate_output_guard(state):
    if state['capture_gaps_over_100ms']:
        raise RuntimeError('output_guard_capture_gap')
    if state.get('reader_error') or state.get('reader_eof'):
        raise RuntimeError('output_guard_reader_stopped')
    if state['nonzero_frames']:
        raise RuntimeError('forbidden_default_output')


def consumer_fault(stack, report, runs):
    # The alternate input is synthetic too. No physical device is in this graph.
    loopback(stack, 'vrct.b.decoy_input')
    Producer(stack, 'vrct.b.decoy_input.sink', 1760)
    set_default('source', 'vrct.b.decoy_input.source')
    decoy_capture = ToneCapture(stack, 'vrct.b.decoy_input.source')
    ready(decoy_capture, 1760)
    report['consumer_faults'] = []
    for index in range(runs):
        with ExitStack() as trial:
            name = f'vrct.b.fault{index}'
            target = loopback(trial, name)
            producer = Producer(trial, name + '.sink', 440)
            strict = ToneCapture(trial, name + '.source')
            permissive = ToneCapture(trial, name + '.source', strict=False)
            ready(strict, 440)
            ready(permissive, 440)
            strict_before, permissive_before = strict.snapshot(), permissive.snapshot()
            fault_ns = time.monotonic_ns()
            producer.close()
            stop_process(target)
            wait_for(lambda: name + '.source' not in nodes())
            # Fixed observation window: a disconnected reader is never called silent.
            time.sleep(2.5)
            strict_after = strict.snapshot()
            permissive_after = permissive.snapshot()
            leaked = strict_after['detected_frames']['1760']
            now_ns = time.monotonic_ns()
            strict_observed = consumer_observation(strict_before, strict_after,
                                                  strict.process.poll(), fault_ns, now_ns)
            permissive_observed = consumer_observation(permissive_before, permissive_after,
                                                      permissive.process.poll(), fault_ns, now_ns)
            report['consumer_faults'].append({
                'index': index, 'strict_forbidden_frames': leaked,
                'strict_process_exit': strict.process.poll(),
                'strict_observation': strict_observed,
                'strict_before': strict_before, 'strict_after': strict_after,
                'permissive_observation': permissive_observed,
                'permissive_before': permissive_before, 'permissive_after': permissive_after,
                'fault_ns': fault_ns, 'observed_ns': now_ns,
                'permissive_forbidden_frames': permissive_after['detected_frames']['1760'],
                'permissive_process_exit': permissive.process.poll(),
                'alternate_source_verified': True, 'vrchat_consumer_tested': False,
            })
            if leaked:
                raise RuntimeError('strict_consumer_fell_back')
            if 'missing' in (strict_observed, permissive_observed):
                raise RuntimeError('consumer_observation_missing')
        print(json.dumps({'consumer_fault': index + 1, 'of': runs}), flush=True)


def exercise(stack, report, runs, soak_seconds):
    loopback(stack, 'vrct.b.decoy_output')
    set_default('sink', 'vrct.b.decoy_output.sink')
    guard = ToneCapture(stack, 'vrct.b.decoy_output.source')
    loopback(stack, 'vrct.b.final')
    route(stack, 'vrct.b.vc')
    route(stack, 'vrct.b.tts')
    capture = ToneCapture(stack, 'vrct.b.final.source')
    vc = Producer(stack, 'vrct.b.vc.sink', 440)
    bus = new_bus(stack)
    for index in range(runs):
        trial = {'index': index, 'status': 'started'}
        report['trials'].append(trial)
        if not bus.publish(make_event(f'{index}-mix')):
            raise RuntimeError('tts_publish_rejected')
        ready(capture, 440, 880)
        trial['tts_cancel'] = measure(report, capture, 'tts_cancel_to_tts_absent', bus.cancel,
                                      absent=(880, 1760), present=(440,))
        wait_for(lambda: idle(bus))
        bus.publish(make_event(f'{index}-restart'))
        ready(capture, 440, 880)
        trial['vc_gate'] = measure(report, capture, 'vc_gate_to_vc_absent',
                                   lambda: mute('vrct.b.vc.sink', True), absent=(440, 1760), present=(880,))
        mute('vrct.b.vc.sink', False)
        ready(capture, 440, 880)
        trial['global_mute'] = measure(report, capture, 'global_mute_to_silence',
                                       lambda: mute('vrct.b.final.source', True), silent=True)
        held_nonzero = capture.snapshot()['nonzero_frames']
        # Recreate both engine substitutes and publish a new TTS while globally muted.
        bus.close()
        vc.close()
        vc = Producer(stack, 'vrct.b.vc.sink', 440)
        bus = new_bus(stack)
        bus.publish(make_event(f'{index}-muted-new'))
        held_since = time.monotonic_ns()
        confirm_mute_hold(capture, held_since, held_nonzero)
        trial['mute_held_after_producer_recreation'] = True
        mute('vrct.b.final.source', False)
        ready(capture, 440, 880)
        # Abrupt VC process loss must leave the endpoint and TTS alive.
        trial['vc_crash'] = measure(report, capture, 'vc_crash_to_vc_absent',
                                    vc.output.process.kill, absent=(440, 1760), present=(880,))
        trial['endpoint_survived_vc_crash'] = 'vrct.b.final.source' in nodes()
        if not trial['endpoint_survived_vc_crash']:
            raise RuntimeError('endpoint_lost_with_producer')
        vc.close()
        vc = Producer(stack, 'vrct.b.vc.sink', 440)
        ready(capture, 440, 880)
        bus.cancel()
        wait_for(lambda: idle(bus))
        trial['status'] = 'passed'
        print(json.dumps({'trial': index + 1, 'of': runs, 'status': 'passed'}), flush=True)
    bus.publish(make_event('soak'))
    ready(capture, 440, 880)
    before = capture.snapshot()
    started = time.monotonic()
    checkpoints = 0
    next_progress = started + 30
    while time.monotonic() - started < soak_seconds:
        time.sleep(min(0.2, max(0, soak_seconds - (time.monotonic() - started))))
        if capture.settled(0, present=(440, 880), absent=(1760,), duration_ms=100) is None:
            raise RuntimeError('soak_signal_gap')
        if bus.status()['errors'] or vc.failure:
            raise RuntimeError('soak_producer_failed')
        checkpoints += 1
        if time.monotonic() >= next_progress:
            print(json.dumps({'soak_elapsed_s': round(time.monotonic() - started)}), flush=True)
            next_progress += 30
    after = capture.snapshot()
    report['soak'] = {'requested_seconds': soak_seconds, 'elapsed_seconds': time.monotonic() - started,
                      'checkpoints': checkpoints, 'before': before, 'after': after,
                      'physical_clock_drift_measured': False, 'gpu_contention_measured': False}
    for frequency in ('440', '880'):
        if after['detected_frames'][frequency] - before['detected_frames'][frequency] != after['frames'] - before['frames']:
            raise RuntimeError('soak_missing_tone_frame')
    if after['capture_gaps_over_100ms'] != before['capture_gaps_over_100ms']:
        raise RuntimeError('soak_capture_gap')
    bus.cancel()
    wait_for(lambda: idle(bus))
    ready(capture, 440)
    report['main_capture'] = capture.snapshot()
    consumer_fault(stack, report, runs)
    settled(guard, time.monotonic_ns(), 'output_guard_not_live_silent', silent=True)
    report['output_guard'] = guard.snapshot()
    validate_output_guard(report['output_guard'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=30)
    parser.add_argument('--soak-seconds', type=float, default=60)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.runs <= 100 or not 0 <= args.soak_seconds <= 7200:
        parser.error('runs must be 1..100; soak-seconds must be 0..7200')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 1, 'status': 'failed', 'os': platform.platform(), 'python': platform.python_version(),
              'graph': 'private_pipewire_policy_only', 'sample_rate': RATE, 'channels': 1,
              'observation_frame_ms': 20, 'tone_threshold_s16': 400, 'silence_peak_threshold_s16': 64,
              'raw_audio_saved': False, 'real_vc_verified': False, 'vrchat_verified': False,
              'ui_verified': False, 'windows_verified': False, 'physical_microphone_captured': False,
              'requested_trials': args.runs, 'rows': [], 'trials': [], 'versions': {}}
    try:
        with private_graph() as stack:
            for binary in ('pipewire', 'wireplumber'):
                report['versions'][binary] = subprocess.run([binary, '--version'], capture_output=True,
                                                            text=True, check=True, timeout=3).stdout.strip()
            exercise(stack, report, args.runs, args.soak_seconds)
            report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as exc:
        report['failure_type'] = type(exc).__name__
        if isinstance(exc, (RuntimeError, TimeoutError)):
            report['failure_code'] = str(exc)
    finally:
        report['summary'] = summarize(report['rows'])
        report['stop_budget'] = {'p95_target_ms': 100, 'worst_target_ms': 250,
                                'all_measured_groups_meet': bool(report['summary']) and all(
                                    group['p95_ms'] <= 100 and max(
                                        (row['end_ns'] - row['start_ns']) / 1e6 for row in report['rows']
                                        if row['metric'] == group['metric']) <= 250
                                    for group in report['summary'])}
        if report['status'] == 'passed' and not report['stop_budget']['all_measured_groups_meet']:
            report['status'] = 'failed'
            report['failure_code'] = 'stop_budget_exceeded'
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        with (args.output / 'timings.csv').open('w', encoding='utf-8', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=['metric', 'environment', 'warm', 'start_ns', 'end_ns'])
            writer.writeheader()
            writer.writerows(report['rows'])
    print(json.dumps({'status': report['status'], 'summary': report['summary'],
                      'failure_code': report.get('failure_code')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
