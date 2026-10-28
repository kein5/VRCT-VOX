# SPDX-License-Identifier: GPL-3.0-only
"""File-input real VC + private OS route; no physical mic or host defaults."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
from threading import Event, Thread
import time

from tools.voice_acceptance import (
    graph_snapshot, loopback, private_graph, stop_process, wait_for,
)
from tools.voice_b_poc import Producer, ToneCapture, set_default
from tools.source_bridge_acceptance import active, check_capture
from models.audio_routing.devices_pipewire import PipeWireOutput
from models.audio_routing.pipewire_gate import PipeWireGate
from models.audio_routing.source_bridge import SourceBridge, select_source
from models.tts.speechcpp_tts import CancelToken
from .packets import read_packet
from .profiles import PROFILES
from .blocks import require_fresh_block

ROOT = Path(__file__).resolve().parents[2]


class PacketDeadline:
    """Apply the same two-block age limit throughout cancellable OS writes."""
    def __init__(self, token, due_ns, block_ms):
        if type(due_ns) is not int or due_ns <= 0 or due_ns > time.monotonic_ns():
            raise ValueError('invalid_packet_timestamp')
        self.token, self.due_ns, self.block_ms = token, due_ns, block_ms

    def check(self):
        self.token.check()
        require_fresh_block(self.due_ns, time.monotonic_ns(), self.block_ms)


class WorkerRoute:
    """PoC supervisor: inference EOF/failure closes the existing source gate."""
    def __init__(self, root, log, profile='baseline'):
        self.token = CancelToken()
        self.bridge = SourceBridge()
        self.bridge.configure(select_source(graph_snapshot(), 'vrct.seed.output.source'))
        self.output = PipeWireOutput('vrct.seed.output.sink', 48000, 1)
        self.packets = []
        self.ready, self.done = Event(), Event()
        self.reason = None
        self.closed_ns = None
        self.forwarding = False
        try:
            self.child = subprocess.Popen([str(root / 'venv/bin/python'), '-u', '-m',
                'integrations.seed_vc.worker', '--engine', str(root / 'engine'),
                '--assets', str(root / 'assets'), '--reference', str(root / 'private-inputs/reference.wav'),
                '--input', str(root / 'private-inputs/input.wav'), '--profile', profile],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, bufsize=0)
        except Exception:
            self.token.cancel()
            try:
                self.output.close(drain=False, token=self.token)
            finally:
                self.bridge.close()
            raise
        self.reader = Thread(target=self.pump, daemon=True)
        self.reader.start()

    def command(self, value):
        self.child.stdin.write((value + '\n').encode())
        self.child.stdin.flush()

    def prepare_route(self):
        # This private source receives PCM only from validated worker packets.
        # Preparing OS links does not authorize or emit an unconverted sample.
        self.bridge.start()
        active(self.bridge)
        self.forwarding = True

    def pump(self):
        try:
            header, pcm = read_packet(self.child.stdout)
            if header['state'] != 'ready' or pcm:
                raise ValueError('worker_not_ready')
            block_ms = header.get('block_ms')
            if type(block_ms) not in (int, float) or not 0 < block_ms <= 1000:
                raise ValueError('invalid_worker_block_time')
            self.ready.set()
            while not self.token.is_set():
                header, pcm = read_packet(self.child.stdout, timeout=1)
                self.packets.append(header)
                if header['state'] not in ('converted', 'vad_silence') or not pcm:
                    self.reason = 'worker_' + header['state']
                    break
                deadline = PacketDeadline(self.token, header.get('input_due_ns'), block_ms)
                deadline.check()
                if not self.forwarding:
                    if header['state'] != 'converted' or not any(pcm):
                        continue
                    self.prepare_route()
                deadline.check()
                self.output.write(pcm, deadline)
                deadline.check()
        except Exception as exc:
            self.reason = type(exc).__name__
        finally:
            try:
                self.bridge.stop()
                self.token.cancel()
                self.output.close(drain=False, token=self.token)
            finally:
                if self.child.poll() is None:
                    self.child.terminate()
                self.closed_ns = time.monotonic_ns()
                self.done.set()

    def stop(self):
        self.token.cancel()
        self.bridge.stop()
        if self.child.poll() is None:
            self.child.terminate()

    def close(self):
        self.stop()
        stop_process(self.child)
        self.reader.join(4)
        if self.reader.is_alive():
            raise RuntimeError('vc_reader_not_stopped')
        if not self.bridge.close():
            raise RuntimeError('vc_bridge_not_stopped')
        self.child.stdin.close()
        self.child.stdout.close()


def trial(root, destination, case, profile='baseline', prime_route=False):
    row = {'case': case, 'profile': profile, 'route_prepared_before_input': prime_route}
    with private_graph(config_fragment=ROOT / 'config/pipewire/90-vrct-managed.conf') as stack:
        loopback(stack, 'vrct.seed.output')
        loopback(stack, 'vrct.seed.decoy')
        decoy = Producer(stack, 'vrct.seed.decoy.sink', 1760)
        set_default('source', 'vrct.seed.decoy.source')
        gate = PipeWireGate()
        gate.set_muted(False, gate.inspect()['identity'])
        capture = ToneCapture(stack, 'vrct.managed.source')
        initial = capture.snapshot()
        with ExitStack() as owned:
            log = owned.enter_context((destination / (case + '-worker.log')).open('wb'))
            route = WorkerRoute(root, log, profile)
            owned.callback(route.close)
            wait_for(lambda: route.ready.is_set() or route.done.is_set(), timeout=60)
            if not route.ready.is_set() or route.done.is_set():
                raise RuntimeError('model_worker_failed_before_ready')
            if prime_route:
                route.prepare_route()
            silent_before = time.monotonic_ns()
            wait_for(lambda: capture.settled(silent_before, silent=True, duration_ms=300))
            row['ready_bridge_active'] = route.bridge.health()['active']
            row['ready_silence_confirmed'] = True
            route.command('start')
            wait_for(lambda: capture.snapshot()['nonzero_frames'] >= initial['nonzero_frames'] + 10,
                     timeout=15, code='real_vc_not_observed')
            row['bridge_during'] = route.bridge.health()
            if not row['bridge_during']['active']:
                raise RuntimeError('vc_bridge_not_active')
            before = capture.snapshot()
            started = time.monotonic_ns()
            if case == 'control':
                # Same phase as fault trials, but leave conversion running.
                time.sleep(2.1)
                continued = capture.snapshot()
                check_capture(before, continued)
                if (continued['nonzero_frames'] - before['nonzero_frames'] < 20
                        or capture.settled(started, silent=True)):
                    raise RuntimeError('continuous_voice_control_failed')
                row['continued_without_stop'] = True
                started = time.monotonic_ns()
                route.stop()
            elif case == 'stop':
                route.stop()
            elif case == 'death':
                route.child.kill()
            else:
                route.command(case)
            first = wait_for(lambda: capture.settled(started, silent=True, absent=(1760,)),
                             timeout=8, code='vc_did_not_become_silent')
            after = capture.snapshot()
            check_capture(initial, after)
            check_capture(before, after)
            wait_for(route.done.is_set, timeout=3)
            row.update(stop_request_ns=started, first_silent_read_ns=first,
                stop_to_silent_read_ms=(first - started) / 1e6,
                silent_confirmation_ms=(after['last_read_ns'] - first) / 1e6,
                gate_closed_ms=(route.closed_ns - started) / 1e6,
                worker_reason=route.reason, bridge_after=route.bridge.health(),
                capture=after, packets=list(route.packets))
            # The capture ran continuously: a dead reader cannot pass the silence check.
            if row['bridge_after']['active'] or decoy.failure:
                raise RuntimeError('vc_route_not_closed')
            with capture.lock:
                heard = [stamp for stamp, _, nonzero in capture.history if nonzero and stamp >= silent_before]
            onsets = [p.get('source_onset_ns') for p in route.packets if p.get('source_onset_ns')]
            row['simulated_source_to_first_read_ms'] = ((min(heard) - min(onsets)) / 1e6
                                                        if heard and onsets else None)
            row['status'] = 'passed'
    row['private_graph_cleaned'] = True
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--poc-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=PROFILES, default='baseline')
    parser.add_argument('--prime-route', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'trials': [], 'physical_input': False,
        'vrchat_tested': False, 'host_audio_changed': False, 'perceptual_quality_verified': False,
        'scope': 'permitted synthetic file released in real time -> VC -> private OS virtual microphone; no physical latency'}
    try:
        for case in ('stop', 'bypass', 'fault', 'death', 'hold', 'slow', 'control'):
            row = trial(args.poc_root.resolve(), args.output, case, args.profile, args.prime_route)
            report['trials'].append(row)
            print(json.dumps({k: row[k] for k in ('case', 'status', 'stop_to_silent_read_ms',
                  'simulated_source_to_first_read_ms')}), flush=True)
        report['status'] = 'passed'
        return 0
    except Exception as exc:
        report.update(status='failed', failure=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
