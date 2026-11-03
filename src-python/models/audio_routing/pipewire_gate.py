"""Inspect named managed nodes; mutate a bound identity with a tiny native helper."""
from pathlib import Path
import subprocess
from runtime_paths import resource_root, external_process_env
import sys
import time

from .pipewire_graph import GraphUnavailable, graph_source, read_graph

SOURCE = 'vrct.managed.source'
TTS_SINK = 'vrct.managed.tts'
VC_SINK = 'vrct.managed.vc'
REQUIRED = {SOURCE: 'Audio/Source', TTS_SINK: 'Audio/Sink',
            VC_SINK: 'Audio/Sink', 'vrct.managed.mix': 'Audio/Sink'}


def parse_graph(data, *, direct=False):
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
        source = found[VC_SINK if direct else SOURCE]
        muted = [p['mute'] for p in source['params']['Props'] if 'mute' in p]
        serial = source['props']['object.serial']
        if len(muted) != 1 or type(muted[0]) is not bool or type(serial) is not int or type(cores[0]) is not int:
            raise ValueError()
        return {'identity': (cores[0], serial), 'muted': muted[0]}
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError('managed_endpoint_missing_or_invalid') from exc


class PipeWireGate:
    def __init__(self, helper=None):
        self.helper = Path(helper) if helper else resource_root() / 'build/vrct-voice-gate'
        self._observer = None

    def observe(self, enabled, wake):
        if enabled and self._observer is None:
            try:
                self._observer = graph_source().subscribe(wake)
            except GraphUnavailable as exc:
                raise RuntimeError('managed_graph_unavailable') from exc
        elif not enabled:
            self.close_observer()

    def close_observer(self):
        if self._observer is not None:
            self._observer.close()
            self._observer = None

    def prepare(self):
        from .managed_microphone import ManagedMicrophone
        ManagedMicrophone(self._snapshot).ensure()

    def inspect(self, *, after=None):
        return parse_graph(self._snapshot(after=after))

    def inspect_pair(self, *, after=None):
        data = self._snapshot(after=after)
        return {'source': parse_graph(data), 'direct': parse_graph(data, direct=True)}

    def _snapshot(self, *, after=None):
        if not sys.platform.startswith('linux'):
            raise RuntimeError('managed_route_linux_only')
        try:
            return read_graph(after=after).data
        except GraphUnavailable as exc:
            raise RuntimeError('managed_graph_unavailable') from exc

    def set_muted(self, value, expected_identity):
        return self._set_muted(value, expected_identity, direct=False)

    def set_direct_muted(self, value, expected_identity):
        return self._set_muted(value, expected_identity, direct=True)

    def resume(self, expected_identity, expected_direct_identity, suppress_direct):
        if not self.helper.is_file():
            raise RuntimeError('voice_gate_helper_missing')
        if expected_identity[0] != expected_direct_identity[0]:
            raise RuntimeError('direct_gate_identity_changed')
        try:
            subprocess.run([str(self.helper), *(str(x) for x in expected_identity),
                '0', 'guard-direct', str(expected_direct_identity[1]), '1' if suppress_direct else '0'], env=external_process_env(),
                check=True, capture_output=True, timeout=2.5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError('gate_identity_or_control_failed') from exc
        pair = self.inspect_pair(after=time.monotonic())
        if pair['source']['identity'] != expected_identity or pair['source']['muted']:
            raise RuntimeError('gate_change_unconfirmed')
        if (pair['direct']['identity'] != expected_direct_identity
                or pair['direct']['muted'] != suppress_direct):
            raise RuntimeError('direct_gate_change_unconfirmed')
        return pair

    def _set_muted(self, value, expected_identity, *, direct):
        if not self.helper.is_file():
            raise RuntimeError('voice_gate_helper_missing')
        try:
            subprocess.run([str(self.helper), *(str(x) for x in expected_identity), '1' if value else '0',
                            *(['vc'] if direct else [])], env=external_process_env(),
                           check=True, capture_output=True, timeout=2.5)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError('gate_identity_or_control_failed') from exc
        after = time.monotonic()
        state = self.inspect_pair(after=after)['direct'] if direct else self.inspect(after=after)
        if state['identity'] != expected_identity:
            raise RuntimeError('managed_endpoint_changed')
        if state['muted'] != value:
            raise RuntimeError('gate_change_unconfirmed')
        return state
