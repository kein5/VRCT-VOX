"""Experimental KDE/Wayland VRChat local mic-test runner (prepared GUI required).

Does not launch applications or install routes. Requires an already running
private ydotoold, a verified virtual mic, an isolated VRChat playback sink,
and local screenshots of the Ready and Recording states. Screenshots/PCM stay
in the selected artifact directory. Use uv run --no-project python ... --help.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
from threading import Thread
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.vrchat_audio_probe import compare_pcm, silence_pcm  # noqa: E402

RATE = 48000


def image_score(a, b):
    if not a or len(a) != len(b):
        return 0
    aa, bb = sum(a) / len(a), sum(b) / len(b)
    denominator = math.sqrt(sum((v - aa) ** 2 for v in a) * sum((v - bb) ** 2 for v in b))
    return sum((x - aa) * (y - bb) for x, y in zip(a, b)) / denominator if denominator else 0


def state_matches(scores, state):
    # Calibrated against both hover states, Recording and initial Start Test.
    return scores[state] >= .8 and scores[state] - max(v for k, v in scores.items() if k != state) >= .2


def capture_valid(samples, elapsed, last_read, max_gap, rate):
    return (elapsed >= 2 and abs(samples / rate - elapsed) < .25
            and 0 <= elapsed - last_read < .3 and max_gap < .3)


def require_focus(expected, query):
    if query().strip() != expected:
        raise RuntimeError('focus_changed')


def command(*args):
    return subprocess.check_output(args, text=True, timeout=10).strip()


def pixels(path):
    # This PoC is calibrated to the Japanese desktop Audio & Voice page,
    # with Volume collapsed. Both test buttons are included in the ROI.
    return subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-vf',
        'crop=iw*0.17:ih*0.05:iw*0.59:ih*0.605,scale=272:64,format=gray',
        '-f', 'rawvideo', '-threads', '1', '-'], timeout=5)


class GUI:
    def __init__(self, window, socket, output, ready, recording):
        self.window, self.output = window, output
        self.env = {**os.environ, 'YDOTOOL_SOCKET': str(socket)}
        self.templates = {'ready': pixels(ready), 'recording': pixels(recording)}
        self.size = struct.unpack('>II', ready.read_bytes()[16:24])
        if image_score(*self.templates.values()) > .9:
            raise RuntimeError('templates_not_distinguishable')
        self.index = 0
        self.observations = []

    def guard(self):
        require_focus(self.window, lambda: command('kdotool', 'getactivewindow'))

    def geometry(self):
        geometry = command('kdotool', 'getwindowgeometry', self.window)
        x, y = map(int, re.search(r'Position: (-?\d+),(-?\d+)', geometry).groups())
        w, h = map(int, re.search(r'Geometry: (\d+)x(\d+)', geometry).groups())
        if w != self.size[0] or not 0 <= h - self.size[1] <= 60:
            raise RuntimeError('window_geometry_changed')
        return x, y + h - self.size[1]

    def observe(self):
        self.move(.40, .26)  # Keep the in-game cursor and hover tint outside the button ROI.
        self.guard()
        self.geometry()
        self.index += 1
        path = self.output / f'screen-{self.index:03d}.png'
        subprocess.run(['spectacle', '-a', '-b', '-n', '-e', '-S', '-o', str(path)],
                       check=True, timeout=10)
        self.guard()
        if struct.unpack('>II', path.read_bytes()[16:24]) != self.size:
            raise RuntimeError('screenshot_size_changed')
        actual = pixels(path)
        scores = {key: image_score(actual, template) for key, template in self.templates.items()}
        self.observations.append({'image': path.name, 'scores': scores})
        return scores

    def wait_state(self, state, timeout=18):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if state_matches(self.observe(), state):
                return
            time.sleep(.25)
        raise RuntimeError(f'gui_{state}_timeout')

    def move(self, x_fraction, y_fraction):
        self.guard()
        x, y = self.geometry()
        px = x + round(x_fraction * self.size[0])
        py = y + round(y_fraction * self.size[1])
        for _ in range(24):
            self.guard()
            location = command('kdotool', 'getmouselocation', '--shell')
            cx, cy = map(int, re.search(r'X=(-?\d+)\nY=(-?\d+)', location).groups())
            dx, dy = px - cx, py - cy
            if max(abs(dx), abs(dy)) <= 2:
                break
            dx = round(dx / 2) or (1 if dx > 0 else -1) if dx else 0
            dy = round(dy / 2) or (1 if dy > 0 else -1) if dy else 0
            subprocess.run(['ydotool', 'mousemove', '-x', str(dx), '-y', str(dy)],
                           env=self.env, check=True, timeout=5)
            time.sleep(.08)
        else:
            raise RuntimeError('pointer_did_not_converge')

    def click(self, x_fraction, y_fraction):
        self.move(x_fraction, y_fraction)
        self.guard()
        try:
            subprocess.run(['ydotool', 'click', '0xC0'], env=self.env, check=True, timeout=5)
        finally:
            subprocess.run(['ydotool', 'click', '0x80'], env=self.env, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Capture:
    def __init__(self, target, path, monitor=False, *, rate=RATE):
        if type(rate) is not int or rate not in (24000, 48000):
            raise ValueError('unsupported_capture_rate')
        self.rate = rate
        props = '{ node.dont-fallback=true node.dont-reconnect=true'
        props += ' stream.capture.sink=true' if monitor else ''
        props += ' }'
        self.file = path.open('wb')
        self.stderr = path.with_suffix('.log').open('wb')
        self.start = time.monotonic()
        self.last = self.start
        self.count, self.max_gap = 0, 0
        self.error = None
        self.process = subprocess.Popen([
            'pw-cat', '--record', '--raw', '--format', 's16', '--rate', str(self.rate),
            '--channels', '1', '--latency', '20ms', '--target', target,
            '--properties', props, '-'], stdout=subprocess.PIPE, stderr=self.stderr)
        self.thread = Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while data := self.process.stdout.read(1920):
                now = time.monotonic()
                if self.count:
                    self.max_gap = max(self.max_gap, now - self.last)
                self.file.write(data)
                self.count += len(data) // 2
                self.last = now
        except Exception as exc:
            self.error = type(exc).__name__

    def close(self):
        end = time.monotonic()
        early = self.process.poll() is not None
        if not early:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.thread.join(3)
        self.process.stdout.close()
        self.file.close()
        self.stderr.close()
        return {'valid': not early and not self.thread.is_alive() and self.error is None
                and capture_valid(self.count, end - self.start,
                                  min(end, self.last) - self.start, self.max_gap, self.rate),
                'samples': self.count, 'elapsed_seconds': end - self.start,
                'last_read_seconds': self.last - self.start, 'max_read_gap_seconds': self.max_gap,
                'early_exit': early, 'reader_error': self.error}


def verify_route(source, sink):
    data = json.loads(command('pw-dump'))
    nodes = {n['id']: n['info']['props'] for n in data if n['type'] == 'PipeWire:Interface:Node'}
    edges = [(nodes[n['info']['output-node-id']], nodes[n['info']['input-node-id']])
             for n in data if n['type'] == 'PipeWire:Interface:Link']
    voice = [(a, b) for a, b in edges if b.get('application.name') == 'VRChat.exe']
    playback = [(a, b) for a, b in edges if a.get('application.name') == 'VRChat.exe']
    incoming = [(a, b) for a, b in edges if b.get('node.name') == sink]
    if not voice or any(a.get('node.name') != source for a, _ in voice):
        raise RuntimeError('vrchat_microphone_route_unverified')
    if not playback or any(b.get('node.name') != sink for _, b in playback):
        raise RuntimeError('vrchat_playback_route_unverified')
    if any(a.get('application.name') != 'VRChat.exe' for a, _ in incoming):
        raise RuntimeError('playback_sink_not_isolated')
    selected = [n for n in nodes.values() if n.get('node.name') in (source, sink)]
    if len(selected) != 2:
        raise RuntimeError('ambiguous_route_identity')
    core = [n['info']['cookie'] for n in data if n['type'] == 'PipeWire:Interface:Core']
    return {'core': core, 'nodes': {n['node.name']: n['object.serial'] for n in selected},
            'edges': sorted(set((a.get('node.name'), b.get('node.name')) for a, b in voice + playback))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('window', 'socket', 'source', 'input-sink', 'replay-sink'):
        parser.add_argument('--' + name, required=True)
    for name in ('reference', 'ready-image', 'recording-image', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--case', choices=('positive', 'silence', 'double', 'stop'), required=True)
    parser.add_argument('--lead-in', type=float, default=1.5, help='quiet pre-roll after Recording is observed')
    args = parser.parse_args()
    if not 0 <= args.lead_in <= 3:
        parser.error('lead-in must be between 0 and 3 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'case': args.case, 'verdict': 'inconclusive', 'boundary': 'local_VRChat_test_digital_replay',
              'lead_in_seconds': args.lead_in, 'managed_route_tested': False, 'physical_headphone_tested': False}
    captures, player, gui = {}, None, None
    try:
        with wave.open(str(args.reference), 'rb') as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (RATE, 1, 2):
                raise ValueError('expected_48k_s16_mono_reference')
            reference = wav.readframes(wav.getnframes())
        report['route_before'] = verify_route(args.source, args.replay_sink)
        gui = GUI(args.window, args.socket, args.output, args.ready_image, args.recording_image)
        gui.wait_state('ready', 5)
        for key, target in [('mic', args.source), ('replay', args.replay_sink)]:
            captures[key] = Capture(target, args.output / f'{key}.pcm', monitor=key == 'replay')
        started = time.monotonic()
        time.sleep(.5)
        gui.click(.715, .631)
        gui.wait_state('recording', 4)
        if args.case != 'silence':
            time.sleep(args.lead_in)
            player = subprocess.Popen(['pw-cat', '--playback', '--target', args.input_sink,
                                       '--latency', '20ms', '--properties',
                                       '{ node.dont-fallback=true node.dont-reconnect=true }',
                                       str(args.reference)], stdout=subprocess.DEVNULL)
            report['producer_started_seconds'] = time.monotonic() - started
            if args.case == 'stop':
                time.sleep(2)
                player.terminate()
            code = player.wait(timeout=15)
            if args.case != 'stop' and code:
                raise RuntimeError('producer_failed')
            report['producer_exit_seconds'] = time.monotonic() - started
        gui.wait_state('ready', 20)
        if args.case == 'double':
            gui.click(.630, .631)  # Play Again, using the verified Ready state.
            time.sleep(.5)
            gui.wait_state('ready', 15)
        duration = 32 if args.case == 'double' else 24
        time.sleep(max(0, duration - (time.monotonic() - started)))
        report['route_after'] = verify_route(args.source, args.replay_sink)
        if report['route_before'] != report['route_after']:
            raise RuntimeError('route_identity_changed')
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if player is not None and player.poll() is None:
            player.terminate()
            try:
                player.wait(timeout=3)
            except subprocess.TimeoutExpired:
                player.kill()
                player.wait(timeout=3)
        report['captures'] = {key: capture.close() for key, capture in captures.items()}
        report['screens'] = gui.observations if gui else []
    if 'error' not in report and all(c['valid'] for c in report['captures'].values()):
        mic, replay = ((args.output / f'{key}.pcm').read_bytes() for key in ('mic', 'replay'))
        report['replay'] = compare_pcm(reference, replay, RATE)
        report['mic'] = compare_pcm(reference, mic, RATE)
        report['post_stop_last_5s'] = silence_pcm(mic[-RATE * 2 * 5:], RATE, minimum_seconds=5)
        settled = report.get('producer_exit_seconds', 0) + .5
        report['post_stop'] = silence_pcm(mic[int(settled * RATE) * 2:], RATE, minimum_seconds=5)
        report['post_stop']['window_start_seconds'] = settled
        quiet = report['post_stop']['verdict'] == 'pass'
        if args.case == 'silence':
            report['silence_control'] = silence_pcm(mic, RATE)
            valid = report['replay'].get('occurrences') == 0 and report['silence_control']['verdict'] == 'pass'
        elif args.case == 'double':
            valid = report['replay'].get('occurrences') == 2 and report['mic'].get('occurrences') == 1
        elif args.case == 'stop':
            begin = int((report['producer_started_seconds'] + .2) * RATE) * 2
            end = int(report['producer_exit_seconds'] * RATE) * 2
            report['mic_before_stop'] = silence_pcm(mic[begin:end], RATE, minimum_seconds=1)
            valid = report['mic_before_stop']['verdict'] == 'fail' and quiet
        else:
            valid = report['replay'].get('occurrences') == 1 and report['mic'].get('occurrences') == 1 and quiet
        report['verdict'] = 'pass' if valid else 'fail'
    elif 'error' not in report:
        report['error'] = 'incomplete_or_stalled_capture'
    (args.output / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'screens'}, indent=2))
    return 0 if report['verdict'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
