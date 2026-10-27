"""Inspect named managed nodes; mutate a bound identity with a tiny native helper."""
import json
from pathlib import Path
import subprocess
import sys

SOURCE = 'vrct.managed.source'
TTS_SINK = 'vrct.managed.tts'
VC_SINK = 'vrct.managed.vc'
REQUIRED = {SOURCE: 'Audio/Source', TTS_SINK: 'Audio/Sink',
            VC_SINK: 'Audio/Sink', 'vrct.managed.mix': 'Audio/Sink'}


def parse_graph(data):
    try:
        cores = [n['info']['cookie'] for n in data if n['type'] == 'PipeWire:Interface:Core']
        found = {}
        for item in data:
            if item['type'] != 'PipeWire:Interface:Node':
                continue
            props = item['info']['props']
            name = props.get('node.name')
            if name not in REQUIRED:
                continue
            if name in found or props.get('media.class') != REQUIRED[name] or props.get('vrct.managed.route') != 'v1':
                raise ValueError()
            found[name] = item['info']
        if set(found) != set(REQUIRED) or len(cores) != 1:
            raise ValueError()
        source = found[SOURCE]
        muted = [p['mute'] for p in source['params']['Props'] if 'mute' in p]
        serial = source['props']['object.serial']
        if len(muted) != 1 or type(muted[0]) is not bool or type(serial) is not int or type(cores[0]) is not int:
            raise ValueError()
        return {'identity': (cores[0], serial), 'muted': muted[0]}
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError('managed_endpoint_missing_or_invalid') from exc


class PipeWireGate:
    def __init__(self, helper=None):
        self.helper = Path(helper) if helper else Path(__file__).resolve().parents[3] / 'build/vrct-voice-gate'

    def inspect(self):
        if not sys.platform.startswith('linux'):
            raise RuntimeError('managed_route_linux_only')
        try:
            result = subprocess.run(['pw-dump'], capture_output=True, check=True, timeout=1)
            return parse_graph(json.loads(result.stdout))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise RuntimeError('managed_graph_unavailable') from exc

    def set_muted(self, value, expected_identity):
        if not self.helper.is_file():
            raise RuntimeError('voice_gate_helper_missing')
        try:
            subprocess.run([str(self.helper), *(str(x) for x in expected_identity), '1' if value else '0'],
                           check=True, capture_output=True, timeout=2.5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError('gate_identity_or_control_failed') from exc
        state = self.inspect()
        if state['identity'] != expected_identity:
            raise RuntimeError('managed_endpoint_changed')
        if state['muted'] != value:
            raise RuntimeError('gate_change_unconfirmed')
        return state
