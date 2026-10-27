"""Managed-route acceptance with synthetic audio on a private PipeWire daemon.

Boundary: VoiceRoute.mute call -> first silent 20 ms read frame, confirmed by
2 seconds of continuous capture. No physical microphone or VRChat is involved.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.voice_b_poc import (  # noqa: E402
    Producer, SyntheticTTS, ToneCapture, confirm_mute_hold, measure, ready, set_default,
    settled, validate_output_guard,
)
from tools.voice_acceptance import (  # noqa: E402
    VoiceEventBus, VoiceSettings, loopback, make_event, nodes, private_graph, start_process, wait_for,
)
from tools.voice_latency import summarize  # noqa: E402
from models.audio_routing.managed_route import VoiceRoute  # noqa: E402
from models.audio_routing.mute_state import MuteState  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate, SOURCE, TTS_SINK, VC_SINK  # noqa: E402

CONFIG = ROOT / 'config/pipewire/90-vrct-managed.conf'


def confirmed(control):
    return wait_for(lambda: control.status()['ready'] and not control.status()['pending'],
                    code='gate_confirmation_missing')


def new_control(stack, store):
    bus = VoiceEventBus(VoiceSettings(mode='original', routing='managed'),
                        provider_factory=SyntheticTTS, request_timeout=7200)
    stack.callback(bus.close)
    control = VoiceRoute(bus, gate=PipeWireGate(), store=store)
    stack.callback(control.close)
    control.configure(True)
    confirmed(control)
    return bus, control


def exercise(stack, report, store, runs, soak_seconds):
    gate = PipeWireGate()
    wait_for(lambda: {SOURCE, TTS_SINK, VC_SINK, 'vrct.managed.mix'} <= nodes().keys())
    initial = gate.inspect()
    if initial['muted'] is not True:
        raise RuntimeError('daemon_initially_open')
    report['initially_muted'] = True
    report['identity'] = initial['identity']
    for wrong in [(initial['identity'][0] ^ 1, initial['identity'][1]),
                  (initial['identity'][0], initial['identity'][1] + 1)]:
        try:
            gate.set_muted(False, wrong)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('wrong_identity_accepted')
        if not gate.inspect()['muted']:
            raise RuntimeError('wrong_identity_opened_gate')
    report['wrong_cookie_and_serial_rejected'] = True
    loopback(stack, 'vrct.managed.guard')
    set_default('sink', 'vrct.managed.guard.sink')
    guard = ToneCapture(stack, 'vrct.managed.guard.source')
    vc = Producer(stack, VC_SINK, 440)
    capture = ToneCapture(stack, SOURCE)
    bus, control = new_control(stack, store)
    settled(capture, time.monotonic_ns(), 'initial_silence_missing', silent=True)
    for index in range(runs):
        trial = {'index': index, 'status': 'started'}
        report['trials'].append(trial)
        control.resume()
        confirmed(control)
        if not bus.publish(make_event(f'{index}-mix')):
            raise RuntimeError('new_tts_rejected')
        ready(capture, 440, 880)
        trial['stop'] = measure(report, capture, 'managed_mute_to_silence', control.mute, silent=True)
        confirmed(control)
        held = capture.snapshot()['nonzero_frames']
        # Kill the separate VC producer process; the daemon's endpoint must survive.
        vc.output.process.kill()
        vc.close()
        control.close()
        bus.close()
        if gate.inspect()['identity'] != initial['identity']:
            raise RuntimeError('producer_exit_replaced_endpoint')
        bus, control = new_control(stack, store)
        vc = Producer(stack, VC_SINK, 440)
        if bus.publish(make_event(f'{index}-muted-new')):
            raise RuntimeError('muted_tts_accepted')
        confirm_mute_hold(capture, time.monotonic_ns(), held)
        trial.update(status='passed', endpoint_identity_preserved=True,
                     mute_held_after_producer_and_control_recreation=True)
        print(json.dumps({'trial': index + 1, 'of': runs}), flush=True)
    control.resume()
    confirmed(control)
    bus.publish(make_event('soak'))
    ready(capture, 440, 880)
    before, started = capture.snapshot(), time.monotonic()
    while time.monotonic() - started < soak_seconds:
        time.sleep(min(.2, max(0, soak_seconds - (time.monotonic() - started))))
        if capture.settled(0, present=(440, 880), duration_ms=100) is None:
            raise RuntimeError('soak_signal_gap')
        if bus.status()['errors'] or vc.failure:
            raise RuntimeError('soak_producer_failed')
    after = capture.snapshot()
    report['soak'] = {'requested_seconds': soak_seconds, 'elapsed_seconds': time.monotonic() - started,
                      'before': before, 'after': after}
    for f in ('440', '880'):
        if after['detected_frames'][f] - before['detected_frames'][f] != after['frames'] - before['frames']:
            raise RuntimeError('soak_missing_tone_frame')
    if after['capture_gaps_over_100ms'] != before['capture_gaps_over_100ms']:
        raise RuntimeError('soak_capture_gap')
    control.close()
    bus.close()
    settled(capture, time.monotonic_ns(), 'shutdown_not_silent', silent=True)
    # A real controller process is killed while open. Its restart must revoke resume.
    code = '''
import sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from models.tts.tts_scheduler import VoiceEventBus
from models.audio_routing.managed_route import VoiceRoute
from models.audio_routing.mute_state import MuteState
from models.audio_routing.pipewire_gate import PipeWireGate
b=VoiceEventBus(); c=VoiceRoute(b,gate=PipeWireGate(),store=MuteState(Path(sys.argv[2])))
c.configure(True)
def ready():
 deadline=time.monotonic()+5
 while not (c.status()['ready'] and not c.status()['pending']):
  if time.monotonic()>deadline: raise RuntimeError('child_not_ready')
  time.sleep(.01)
ready(); c.resume(); ready()
print('ready',flush=True)
time.sleep(30)
'''
    child = start_process(stack, [sys.executable, '-c', code, str(ROOT / 'src-python'), str(store.path)],
                          stdout=subprocess.DEVNULL)
    ready(capture, 440)
    child.kill()
    child.wait(timeout=2)
    # Explicitly record the limitation: SIGKILL cannot run shutdown's mute.
    ready(capture, 440)
    report['controller_sigkill_gate_stays_open_until_restart'] = not gate.inspect()['muted']
    restarted_bus, restarted = new_control(stack, store)
    settled(capture, time.monotonic_ns(), 'controller_restart_not_silent', silent=True)
    report['controller_process_restart_mutes'] = restarted.status()['observed_muted'] is True
    report['main_capture'] = capture.snapshot()
    if report['main_capture']['capture_gaps_over_100ms']:
        raise RuntimeError('main_capture_gap')
    settled(guard, time.monotonic_ns(), 'guard_not_live_silent', silent=True)
    report['output_guard'] = guard.snapshot()
    validate_output_guard(report['output_guard'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=30)
    parser.add_argument('--soak-seconds', type=float, default=60)
    args = parser.parse_args(argv)
    if not 1 <= args.runs <= 100 or not 0 <= args.soak_seconds <= 7200:
        parser.error('runs must be 1..100; soak-seconds must be 0..7200')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 1, 'status': 'failed', 'os': platform.platform(), 'python': platform.python_version(),
              'boundary': 'VoiceRoute.mute call to first silent read frame; 2s confirmation',
              'graph': 'private_pipewire_policy_only', 'sample_rate': 48000, 'channels': 1,
              'observation_frame_ms': 20, 'tone_threshold_s16': 400, 'silence_peak_threshold_s16': 64,
              'requested_trials': args.runs, 'rows': [], 'trials': [], 'versions': {},
              'vrchat_verified': False, 'real_vc_verified': False, 'windows_verified': False,
              'ui_verified': False, 'gpu_contention_measured': False,
              'raw_audio_saved': False, 'physical_microphone_captured': False,
              'config_sha256': hashlib.sha256(CONFIG.read_bytes()).hexdigest()}
    try:
        with tempfile.TemporaryDirectory(prefix='vrct-managed-state-') as temp:
            store = MuteState(Path(temp) / 'voice_mute_state.json')
            with private_graph(config_fragment=CONFIG) as stack:
                for binary in ('pipewire', 'wireplumber'):
                    report['versions'][binary] = subprocess.run([binary, '--version'], capture_output=True,
                                                                text=True, check=True, timeout=3).stdout.strip()
                exercise(stack, report, store, args.runs, args.soak_seconds)
            # A fresh daemon with a persisted previous resume must still boot closed.
            store.write(False)
            with private_graph(config_fragment=CONFIG) as stack:
                wait_for(lambda: SOURCE in nodes())
                initial = PipeWireGate().inspect()
                if not initial['muted'] or initial['identity'][0] == report['identity'][0]:
                    raise RuntimeError('fresh_daemon_not_muted')
                Producer(stack, VC_SINK, 440)
                capture = ToneCapture(stack, SOURCE)
                bus, control = new_control(stack, store)
                settled(capture, time.monotonic_ns(), 'fresh_daemon_not_silent', silent=True)
                report['fresh_daemon_boots_muted_despite_saved_resume'] = True
                report['fresh_daemon_cookie_changed'] = True
            report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as exc:
        report['failure_type'] = type(exc).__name__
        report['failure_code'] = str(exc) if isinstance(exc, (RuntimeError, TimeoutError)) else type(exc).__name__
    finally:
        report['summary'] = summarize(report['rows'])
        report['stop_budget'] = {'p95_target_ms': 100, 'worst_target_ms': 250,
                                'met': bool(report['summary']) and all(g['p95_ms'] <= 100 for g in report['summary'])
                                and all((r['end_ns'] - r['start_ns']) / 1e6 <= 250 for r in report['rows'])}
        if report['status'] == 'passed' and not report['stop_budget']['met']:
            report['status'], report['failure_code'] = 'failed', 'stop_budget_exceeded'
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
