"""Model-free source bridge acceptance on an isolated Linux audio graph.

No physical microphone, host defaults, VC models, or raw PCM artifacts.
Timings are operation -> qualifying 20ms virtual-source read, with 2s proof
of continued observation. They are not inference or VRChat mouth-to-ear times.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import select
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src-python'))

from tools.voice_acceptance import (  # noqa: E402
    graph_snapshot, loopback, nodes, private_graph, start_process, stop_process, wait_for,
)
from tools.voice_b_poc import Producer, ToneCapture, set_default  # noqa: E402
from models.audio_routing.pipewire_gate import PipeWireGate  # noqa: E402
from models.audio_routing.source_bridge import SourceBridge, select_source  # noqa: E402

FRAGMENT = ROOT / 'config/pipewire/90-vrct-managed.conf'


def check_capture(before, after, *, now_ns=None):
    now_ns = time.monotonic_ns() if now_ns is None else now_ns
    if (after['reader_eof'] or after['reader_error'] or after['frames'] <= before['frames']
            or not after['last_read_ns'] or now_ns - after['last_read_ns'] > 200_000_000
            or after['capture_gaps_over_100ms'] != before['capture_gaps_over_100ms']):
        raise RuntimeError('source_bridge_capture_missing')


def observe(record, capture, name, action=lambda: None, *, direct=False):
    before = capture.snapshot()
    start = time.monotonic_ns()
    action()
    first = wait_for(lambda: capture.settled(start, present=(440, 880) if direct else (880,),
                       absent=(1760,) if direct else (440, 1760)), timeout=6, code=name + '_not_observed')
    after = capture.snapshot()
    check_capture(before, after)
    if after['detected_frames']['1760']:
        raise RuntimeError('source_bridge_forbidden_fallback')
    row = {'case': name, 'operation_ns': start, 'first_qualifying_read_ns': first,
           'confirmed_ns': after['last_read_ns'], 'operation_to_read_ms': (first - start) / 1e6,
           'continuous_confirmation_ms': (after['last_read_ns'] - first) / 1e6}
    record['cases'].append(row)
    print(json.dumps({'trial': record['index'], **row}), flush=True)


def close_bridge(bridge):
    if not bridge.close():
        raise RuntimeError('source_bridge_worker_not_closed')


def active(bridge):
    def ready():
        state = bridge.health()
        if state['error']:
            raise RuntimeError(state['error'])
        return state['active']
    wait_for(ready, timeout=4)


# Fault-injection subprocess. The thread case deliberately disables Python
# cleanup to prove that the native parent-thread death guard closes real audio.
LIFETIME_SCRIPT = '''
import json, os, sys, threading, time
from models.audio_routing import source_bridge as m
fault = threading.Event()
original_links = m._links
def links(*args, **kwargs):
    if fault.is_set(): raise SystemExit()
    return original_links(*args, **kwargs)
if sys.argv[1] == 'thread':
    m._links = links
    m._reap = lambda child: None
bridge = m.SourceBridge()
bridge.configure(m.select_source(m._read_graph(), 'vrct.bridge.input.source'))
bridge.start()
deadline = time.monotonic() + 4
while not bridge.health()['active']:
    if bridge.health()['error'] or time.monotonic() > deadline: sys.exit(1)
    time.sleep(.01)
print(json.dumps({'tag': bridge._run.tag, 'pid': bridge._run.child.pid}), flush=True)
input()
if sys.argv[1] == 'parent': os._exit(0)
fault.set()
bridge._run.thread.join(3)
print('thread-ended', flush=True)
input()
'''


def readline(process):
    if not select.select([process.stdout], [], [], 5)[0]:
        raise RuntimeError('source_bridge_lifetime_child_timeout')
    line = process.stdout.readline()
    if not line:
        raise RuntimeError('source_bridge_lifetime_child_failed')
    return line


def lifetime_case(stack, record, capture, mode):
    parent = start_process(stack, [sys.executable, '-u', '-c', LIFETIME_SCRIPT, mode],
                           env={**os.environ, 'PYTHONPATH': str(ROOT / 'src-python')},
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    owned = json.loads(readline(parent))
    name = f"vrct.source-bridge.{owned['tag']}.playback"
    observe(record, capture, mode + '_ready', direct=True)

    def trigger():
        parent.stdin.write('fault\n')
        parent.stdin.flush()
        if mode == 'parent':
            parent.wait(timeout=3)
        else:
            if readline(parent).strip() != 'thread-ended' or parent.poll() is not None:
                raise RuntimeError('source_bridge_thread_fault_invalid')

    observe(record, capture, mode + '_death', trigger)
    wait_for(lambda: name not in nodes(), code='source_bridge_orphaned_stream')
    if mode == 'thread':
        parent.stdin.write('exit\n')
        parent.stdin.flush()
        parent.wait(timeout=3)
    parent.stdin.close()
    parent.stdout.close()
    record.setdefault('lifetime', []).append({'mode': mode, 'child_stream_removed': True,
                                            'python_cleanup_bypassed': True})


def exercise_trial(stack, record):
    record['cases'] = []
    gate = PipeWireGate()
    gate.set_muted(False, gate.inspect()['identity'])
    capture = ToneCapture(stack, 'vrct.managed.source')
    initial = capture.snapshot()
    try:
        loopback(stack, 'vrct.bridge.decoy')
        decoy = Producer(stack, 'vrct.bridge.decoy.sink', 1760)
        set_default('source', 'vrct.bridge.decoy.source')
        source_process = loopback(stack, 'vrct.bridge.input')
        source_audio = Producer(stack, 'vrct.bridge.input.sink', 440)
        tts = Producer(stack, 'vrct.managed.tts', 880)
        bridge = SourceBridge()
        stack.callback(close_bridge, bridge)
        selected = select_source(graph_snapshot(), 'vrct.bridge.input.source')
        record['source'] = asdict(selected)
        record['sink_serial'] = nodes()['vrct.managed.vc']['info']['props']['object.serial']
        bridge.configure(selected)
        observe(record, capture, 'configured_closed')
        observe(record, capture, 'start', bridge.start, direct=True)
        active(bridge)
        observe(record, capture, 'stop', bridge.stop)
        close_bridge(bridge)
        observe(record, capture, 'restart', bridge.start, direct=True)
        active(bridge)
        observe(record, capture, 'source_loss', lambda: stop_process(source_process))
        wait_for(lambda: bridge.health()['error'])
        record['source_loss_health'] = bridge.health()
        close_bridge(bridge)
        source_audio.close()
        loopback(stack, 'vrct.bridge.input')
        replacement = Producer(stack, 'vrct.bridge.input.sink', 440)
        observe(record, capture, 'same_name_stays_closed')
        bridge.start()  # Old selection must not be valid for a same-name node.
        wait_for(lambda: bridge.health()['error'])
        record['stale_selection_health'] = bridge.health()
        close_bridge(bridge)
        bridge.configure(select_source(graph_snapshot(), selected.name))
        observe(record, capture, 'explicit_reselect', bridge.start, direct=True)
        active(bridge)
        close_bridge(bridge)
        observe(record, capture, 'closed_before_lifetime')
        for mode in ('parent', 'thread'):
            lifetime_case(stack, record, capture, mode)
        observe(record, capture, 'before_sink_loss', bridge.start, direct=True)
        active(bridge)

        def remove_sink():
            sink = nodes()['vrct.managed.vc']
            subprocess.run(['pw-cli', 'destroy', str(sink['id'])], check=True,
                           capture_output=True, timeout=3)

        observe(record, capture, 'sink_loss', remove_sink)
        wait_for(lambda: bridge.health()['error'])
        record['sink_loss_health'] = bridge.health()
        close_bridge(bridge)
        if any(producer.failure for producer in (tts, decoy, replacement)):
            raise RuntimeError('source_bridge_producer_failed')
        final = capture.snapshot()
        check_capture(initial, final)
        if final['detected_frames']['1760']:
            raise RuntimeError('source_bridge_forbidden_fallback')
        record['status'] = 'passed'
    finally:
        record['capture'] = capture.snapshot()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New report directory')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args(argv)
    if not 1 <= args.runs <= 30:
        parser.error('runs must be 1..30')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 1, 'status': 'failed', 'trials': [], 'os': platform.platform(),
              'real_vc_verified': False, 'host_audio_changed': False, 'raw_pcm_saved': False,
              'physical_microphone_captured': False, 'vrchat_verified': False,
              'boundary': 'operation_to_private_source_read_20ms_frames_2s_continuity'}
    try:
        for index in range(args.runs):
            record = {'index': index, 'status': 'failed'}
            report['trials'].append(record)
            with private_graph(config_fragment=FRAGMENT), ExitStack() as trial:
                # The private graph owns the outer process lifetime; the trial's
                # stack finishes all readers/workers before that graph is torn down.
                exercise_trial(trial, record)
        report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as exc:
        report['failure_type'] = type(exc).__name__
        if isinstance(exc, (RuntimeError, TimeoutError)):
            report['failure_code'] = str(exc)
    finally:
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'failure_code': report.get('failure_code')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
