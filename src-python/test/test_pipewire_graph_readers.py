"""Graph failures reach the existing mute/stop paths, including isolated VC."""
import io
import json
import os
import sys
from threading import current_thread
import time

import pytest

from models.audio_routing import pipewire_graph as pg
from models.audio_routing import pipewire_graph_pipe as transport
from models.audio_routing import pipewire_gate as gate_module
from models.audio_routing import source_bridge as sb
import test_pipewire_graph as fixtures
from test_pipewire_graph import graph, until, node

shared = fixtures.shared

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux audio routing')


class Bus:
    def __init__(self):
        self.muted = None

    def set_muted(self, value):
        self.muted = value


class Store:
    def read(self):
        return True

    def write(self, value):
        pass


@pytest.mark.parametrize('fault', ['cookie', 'serial', 'loss'])
def test_route_replacement_or_loss_mutes_without_auto_resume(shared, monkeypatch, fault):
    from models.audio_routing.managed_route import VoiceRoute
    source, backend = shared
    gate = gate_module.PipeWireGate()
    monkeypatch.setattr(gate, 'prepare', lambda: None)
    def mute(value, identity):
        for item in backend.data[2:]:
            props = item['info']['props']
            if (backend.data[0]['info']['cookie'], props['object.serial']) == identity:
                item['info']['params']['Props'][0]['mute'] = value
                return dict(identity=identity, muted=value)
        raise RuntimeError('managed_endpoint_changed')
    monkeypatch.setattr(gate, 'set_muted', mute)
    def resume(identity, direct_identity, suppress_direct):
        mute(False, identity)
        return dict(source=dict(identity=identity, muted=False),
                    direct=dict(identity=direct_identity, muted=suppress_direct))
    monkeypatch.setattr(gate, 'resume', resume)
    bus = Bus()
    # Graph publication must wake the route before its fallback timer.
    route = VoiceRoute(bus, gate=gate, store=Store(), poll_interval=5)
    try:
        route.configure(True)
        until(lambda: route.status()['ready'] and not route.status()['pending'])
        route.resume()
        until(lambda: bus.muted is False)
        # Wait until the fake graph itself has caught up with the native change.
        until(lambda: source.read(wait=False).data[2]['info']['params']['Props'][0]['mute'] is False)
        if fault == 'cookie':
            backend.data[0]['info']['cookie'] += 1
        elif fault == 'serial':
            backend.data[2]['info']['props']['object.serial'] += 1
        else:
            backend.mode = 'exit'
        until(lambda: bus.muted is True)
        assert route.status()['requested_muted']
        if fault == 'loss':
            until(lambda: route.status()['error'] == 'managed_graph_unavailable')
        else:
            until(lambda: route.status()['ready'] and not route.status()['pending'])
            assert route.status()['observed_muted'] is True
    finally:
        route.close()
    assert source._thread is None


class BridgeChild:
    pid = 1234
    code = None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15

    def kill(self):
        self.code = -9

    def wait(self, timeout):
        return self.code


@pytest.mark.parametrize('fault,code', [('cookie', 'source_bridge_endpoint_changed'),
    ('serial', 'source_bridge_endpoint_changed'), ('link', 'source_bridge_links_missing'),
    ('loss', 'source_bridge_graph_unavailable')])
def test_bridge_reaps_on_shared_graph_failure(shared, monkeypatch, fault, code):
    source, backend = shared
    child = BridgeChild()
    selected = sb.select_source(backend.data, 'external.source')
    sink = sb._sink(backend.data)
    def launch(src, dst, tag):
        assert src == selected and dst == sink
        backend.data += [node(20, f'vrct.source-bridge.{tag}.capture', 120, 'Stream/Input/Audio',
                              **{'vrct.source.bridge': 'v1', 'client.id': 30}),
                         node(21, f'vrct.source-bridge.{tag}.playback', 121, 'Stream/Output/Audio',
                              **{'vrct.source.bridge': 'v1', 'client.id': 30}),
                         dict(type='PipeWire:Interface:Client', id=30,
                              info={'props': {'pipewire.sec.pid': child.pid}})]
        backend.data += [dict(type='PipeWire:Interface:Link', info={
            'output-node-id': a, 'input-node-id': b, 'state': 'active'})
            for a, b in [(10, 20), (21, sb._node(backend.data, sink.name)['id'])]]
        return child
    def unmute(endpoint, tag):
        sb._node(backend.data, endpoint.name)['info']['params']['Props'][0]['mute'] = False
    monkeypatch.setattr(sb, '_launch', launch)
    monkeypatch.setattr(sb, '_unmute', unmute)
    monkeypatch.setattr(sb, 'MONITOR_INTERVAL', 5)
    bridge = sb.SourceBridge()
    try:
        bridge.start(source=selected)
        until(lambda: bridge.health()['active'])
        if fault == 'cookie':
            backend.data[0]['info']['cookie'] += 1
        elif fault == 'serial':
            backend.data[1]['info']['props']['object.serial'] += 1
        elif fault == 'link':
            backend.data.pop()
        else:
            backend.mode = 'exit'
        until(lambda: bridge.health()['error'])
        assert bridge.health()['error'] == code
        assert not bridge.health()['requested'] and not bridge.health()['active']
        until(lambda: child.poll() is not None)
    finally:
        assert bridge.close()
    assert source._thread is None


@pytest.mark.parametrize('fault,code', [('source', 'vc_source_changed'),
    ('sink', 'vc_sink_changed'), ('loss', 'vc_worker_failed'), ('stale', 'vc_worker_failed')])
def test_conversion_audio_loop_only_reads_observations_and_stops(shared, monkeypatch, fault, code):
    from models.voice_conversion import process as vc
    source, backend = shared
    selected = sb.select_source(backend.data, 'external.source')
    read_fd, write_fd = os.pipe()
    child = BridgeChild()
    child.stdin = os.fdopen(write_fd, 'wb', buffering=0)
    child.stdout = io.BytesIO()
    captured, output, checks = [], [], []
    class Capture:
        def __init__(self, *args):
            self.stopped = False
            captured.append(self)
        def start(self):
            pass
        def request_stop(self):
            self.stopped = True
        stop = request_stop
    class Output:
        def close(self, **kwargs):
            output.append('closed')
    process = vc.VCProcess(engine='seed-vc')
    monkeypatch.setattr(process, '_launch_worker', lambda: child)
    monkeypatch.setattr(vc, 'PipeWireCapture', Capture)
    monkeypatch.setattr(vc, '_output', lambda sink: Output())
    monkeypatch.setattr(vc.p, 'read_packet', lambda *a, **kw: (dict(vc.p.ready_info(process._session), pcm_bytes=0), b''))
    binding = vc._binding
    def checked(src, **kwargs):
        checks.append((current_thread().name, kwargs.get('wait', True)))
        return binding(src, **kwargs)
    monkeypatch.setattr(vc, '_binding', checked)
    try:
        process.start(source=selected)
        until(lambda: process.health()['active'])
        if fault == 'source':
            backend.data[1]['info']['props']['object.serial'] += 1
        elif fault == 'sink':
            sb._node(backend.data, gate_module.VC_SINK)['info']['props']['object.serial'] += 1
        elif fault == 'loss':
            backend.mode = 'exit'
        else:
            stamp = source.read(wait=False).captured
            source._clock = lambda: stamp + pg.MAX_AGE
        until(lambda: process.health()['error'])
        assert process.health()['error'] == code
        assert not process.health()['active'] and not process.health()['requested']
        assert any(name == 'vrct-vc' and wait is False for name, wait in checks)
        assert set(backend.threads) == {'vrct-pipewire-graph'}
    finally:
        assert process.close()
        os.close(read_fd)
    assert captured[0].stopped and output == ['closed'] and child.poll() is not None
    assert source._thread is None


def test_parent_feed_and_isolated_reader_share_sequence_and_capture_time(shared):
    source, backend = shared
    feed = transport.GraphFeed(('external.source', gate_module.VC_SINK))
    remote = transport.RemoteGraph(os.dup(feed.read_fd))
    feed.close_reader()
    try:
        with remote.subscribe(), source.subscribe():
            first = remote.read()
            parent = source.read(wait=False)
            assert first.sequence == parent.sequence and first.captured == parent.captured
            assert first.data == [parent.data[0], parent.data[1], sb._node(parent.data, gate_module.VC_SINK)]
            assert len(first.data) == 3  # No full-graph parse in the isolated process.
            assert len(backend.children) == 1
            feed.close()
            until(lambda: remote.observation().data is None)
            with pytest.raises(pg.GraphUnavailable):
                remote.read(wait=False)
    finally:
        feed.close()
        remote.close()
    assert not feed.thread.is_alive() and source._thread is None


@pytest.mark.parametrize('fault', ['stale', 'oversize', 'partial', 'invalid'])
def test_remote_source_rejects_bad_stalled_or_expired_frames(fault):
    read, write = os.pipe()
    remote = transport.RemoteGraph(read)
    data = json.dumps(graph()).encode()
    captured = time.monotonic() - (2 if fault == 'stale' else 0)
    size = pg.MAX_BYTES + 1 if fault == 'oversize' else len(data)
    wire = transport._HEADER.pack(1, captured, size) + data
    if fault == 'partial':
        wire = wire[:5]
    if fault == 'invalid':
        wire = transport._HEADER.pack(1, captured, 2) + b'{}'
    os.write(write, wire)
    try:
        with remote.subscribe():
            with pytest.raises(pg.GraphUnavailable):
                remote.read()
            with pytest.raises(pg.GraphUnavailable):
                remote.read(wait=False)
    finally:
        remote.close()
        os.close(write)


def test_gate_confirmation_requires_capture_after_helper_return(shared, monkeypatch, tmp_path):
    source, backend = shared
    helper = tmp_path / 'gate'
    helper.touch()
    gate = gate_module.PipeWireGate(helper)
    native_return = []
    def run(*args, **kwargs):
        backend.data[2]['info']['params']['Props'][0]['mute'] = False
        native_return.append(time.monotonic())
    monkeypatch.setattr(gate_module.subprocess, 'run', run)
    with source.subscribe():
        source.read()
        state = gate.set_muted(False, (42, 111))
        assert state == dict(identity=(42, 111), muted=False)
        assert source.read(wait=False).captured >= native_return[0]


def test_isolated_python_reads_parent_graph_without_any_dump(shared):
    import subprocess
    from pathlib import Path
    source, backend = shared
    root = Path(__file__).resolve().parents[2]
    script = '''
import json, subprocess
from models.audio_routing.pipewire_graph_pipe import receive_from_parent
from models.voice_conversion.process import _binding
from models.audio_routing.source_bridge import Endpoint

def forbidden(*args, **kwargs):
    raise AssertionError('child attempted a subprocess')
subprocess.Popen = subprocess.run = forbidden
remote = receive_from_parent()
try:
    with remote.subscribe():
        value = remote.read()
        sink = _binding(Endpoint(42, 110, 'external.source', 'Audio/Source'), wait=False)
        print(json.dumps([value.sequence, value.captured, sink.serial]), flush=True)
finally:
    remote.close()
'''
    feed = transport.GraphFeed(('external.source', gate_module.VC_SINK))
    child = None
    try:
        child = subprocess.Popen([sys.executable, '-B', '-c', script],
            env={**os.environ, transport._ENV: str(feed.read_fd), 'PYTHONPATH': str(root / 'src-python')},
            pass_fds=(feed.read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        feed.close_reader()
        stdout, stderr = child.communicate(timeout=3)
        assert child.returncode == 0, stderr.decode()
        sequence, captured, serial = json.loads(stdout)
        assert sequence >= 1 and 0 <= time.monotonic() - captured < pg.MAX_AGE
        assert serial == sb._sink(backend.data).serial
        assert set(backend.threads) == {'vrct-pipewire-graph'}
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        feed.close()
    assert source._thread is None


def test_audio_write_checks_graph_freshness_at_commit(shared):
    from models.voice_conversion.process import _Deadline
    from models.tts.speechcpp_tts import CancelToken
    source, _ = shared
    with source.subscribe():
        observation = source.read()
        deadline = _Deadline(CancelToken(), time.monotonic_ns() - 1_000_000,
                             lambda: source.read(wait=False))
        deadline.check()
        source._clock = lambda: observation.captured + pg.MAX_AGE
        writes = []
        with pytest.raises(pg.GraphUnavailable):
            deadline.commit_audio_write(b'\0\0', lambda: writes.append(True))
        assert not writes


@pytest.mark.parametrize('duplicate', ['core', 'source', 'sink'])
def test_filtered_feed_preserves_ambiguous_endpoint_evidence(shared, duplicate):
    source, backend = shared
    item = (backend.data[0] if duplicate == 'core' else
            sb._node(backend.data, 'external.source' if duplicate == 'source' else gate_module.VC_SINK))
    backend.data.append(item)
    feed = transport.GraphFeed(('external.source', gate_module.VC_SINK))
    remote = transport.RemoteGraph(os.dup(feed.read_fd))
    feed.close_reader()
    try:
        with remote.subscribe():
            data = remote.read().data
            with pytest.raises(RuntimeError, match='source_bridge_endpoint_'):
                if duplicate == 'sink':
                    sb._sink(data)
                else:
                    sb.select_source(data, 'external.source')
    finally:
        remote.close()
        feed.close()
    assert source._thread is None
