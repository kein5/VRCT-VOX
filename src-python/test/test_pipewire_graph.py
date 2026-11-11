"""Shared graph ownership and safety, without connecting to PipeWire."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread, current_thread
import time
from types import SimpleNamespace

import pytest

from models.audio_routing import devices_windows
from models.audio_routing import pipewire_graph as pg
from models.audio_routing import pipewire_gate as gate_module
from models.audio_routing import source_bridge as bridge_module

pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Linux graph observation')


def node(ident, name, serial, media='Audio/Sink', muted=True, **extra):
    return dict(id=ident, type='PipeWire:Interface:Node', info=dict(
        props={'node.name': name, 'object.serial': serial, 'media.class': media, **extra},
        params={'Props': [{'mute': muted}]}))


def graph():
    return [dict(type='PipeWire:Interface:Core', info={'cookie': 42}),
            node(10, 'external.source', 110, 'Audio/Source'),
            *[node(11 + i, name, 111 + i, media, muted=name != gate_module.VC_SINK,
                   **{'vrct.managed.route': 'v1'}) for i, (name, media) in
              enumerate(gate_module.REQUIRED.items())]]


def until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.002)
    raise AssertionError('condition did not become true')


class Dump:
    def __init__(self, data, mode):
        self.stdout = io.BytesIO()
        self.wire = json.dumps(data).encode() if mode != 'malformed' else b'{}'
        self.returncode = None
        self.mode = mode
        self.ready = Event()
        self.killed = False
        self.waited = False
        if mode != 'stall':
            self.ready.set()

    def communicate(self, timeout):
        if not self.ready.wait(timeout):
            raise subprocess.TimeoutExpired('pw-dump', timeout)
        self.returncode = 1 if self.mode == 'exit' else 0
        return self.wire, None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed, self.returncode = True, -9
        self.ready.set()

    def wait(self):
        self.waited = True
        return self.returncode


class Dumps:
    def __init__(self):
        self.data = graph()
        self.mode = 'ok'
        self.children, self.threads = [], []

    def __call__(self, argv, **kwargs):
        assert argv == ['pw-dump']
        assert kwargs['stderr'] == subprocess.DEVNULL
        child = Dump(copy.deepcopy(self.data), self.mode)
        self.children.append(child)
        self.threads.append(current_thread().name)
        return child


@pytest.fixture
def shared(monkeypatch):
    backend = Dumps()
    source = pg.GraphSource(popen=backend)
    monkeypatch.setattr(pg, '_shared', source)
    monkeypatch.setattr(pg, '_remote', None)
    monkeypatch.setattr(pg.sys, 'platform', 'linux')
    yield source, backend
    source.close()
    assert all(child.waited and child.stdout.closed for child in backend.children)


def test_concurrent_gate_bridge_conversion_and_devices_share_one_inflight_dump(shared):
    from models.voice_conversion.process import _binding
    source, backend = shared
    backend.mode = 'stall'
    selected = bridge_module.select_source(backend.data, 'external.source')
    results, failures = [], []
    def read(fn):
        try:
            results.append(fn())
        except Exception as exc:
            failures.append(exc)
    with source.subscribe():
        readers = [Thread(target=read, args=(fn,)) for fn in (
            gate_module.PipeWireGate().inspect_pair, bridge_module.enumerate_sources,
            lambda: _binding(selected), bridge_module.microphone_devices)]
        for thread in readers:
            thread.start()
        until(lambda: backend.children)
        time.sleep(.02)
        assert len(backend.children) == 1
        backend.children[0].ready.set()
        for thread in readers:
            thread.join(1)
            assert not thread.is_alive()
        assert len(results) == 4 and not failures
        observation = source.read(wait=False)
        assert observation.sequence == 1 and observation.captured <= time.monotonic()
        assert len(backend.children) == 1
        assert backend.threads == ['vrct-pipewire-graph']


@pytest.mark.parametrize('fault', ['exit', 'malformed', 'stale', 'dead'])
def test_unavailable_observation_preserves_reader_error_codes(shared, fault):
    from models.voice_conversion.process import _binding
    source, backend = shared
    selected = bridge_module.select_source(backend.data, 'external.source')
    with source.subscribe():
        first = source.read()
        if fault in ('exit', 'malformed'):
            backend.mode = fault
            until(lambda: source.observation().data is None)
        elif fault == 'stale':
            source._clock = lambda: first.captured + pg.MAX_AGE
        else:
            source._stop.set()
            source._thread.join(1)
        for fn, code in ((gate_module.PipeWireGate().inspect_pair, 'managed_graph_unavailable'),
                         (lambda: bridge_module._read_graph(wait=False), 'source_bridge_graph_unavailable'),
                         (lambda: _binding(selected, wait=False), 'source_bridge_graph_unavailable')):
            with pytest.raises(RuntimeError, match=code):
                fn()


def test_freshness_is_measured_before_dump_and_confirmation_waits_past_mutation(shared):
    source, backend = shared
    with source.subscribe():
        first = source.read()
        backend.mode = 'stall'
        until(lambda: len(backend.children) == 2)
        barrier = time.monotonic()
        backend.data[0]['info']['cookie'] += 1
        old = backend.children[1]
        backend.mode = 'ok'
        old.ready.set()
        value = source.read(after=barrier)
        assert value.sequence >= first.sequence + 2
        assert value.captured >= barrier and value.data[0]['info']['cookie'] == 43


def test_last_release_kills_and_reaps_inflight_dump_and_can_restart(shared):
    source, backend = shared
    first, second = source.subscribe(), source.subscribe()
    source.read()
    first.close()
    assert source._thread.is_alive()
    backend.mode = 'stall'
    until(lambda: len(backend.children) == 2)
    second.close()
    assert backend.children[-1].killed and backend.children[-1].waited
    assert source._thread is None
    backend.mode = 'ok'
    with source.subscribe():
        assert source.read().data
    assert source._thread is None


def test_shutdown_reaps_with_users_and_prevents_restart(shared):
    source, backend = shared
    user = source.subscribe()
    source.read()
    backend.mode = 'stall'
    until(lambda: len(backend.children) == 2)
    pg.shutdown()
    user.close()
    assert source._thread is None and backend.children[-1].killed
    with pytest.raises(pg.GraphUnavailable):
        source.subscribe()
    with pytest.raises(pg.GraphUnavailable):
        source.read(wait=False)


def test_non_linux_reads_never_launch(monkeypatch, shared):
    _, backend = shared
    # Windows lists its own endpoints instead of refusing; it must not reach PipeWire either.
    monkeypatch.setattr(devices_windows, 'enumerate_endpoints', lambda source: [])
    for platform in ('win32', 'darwin'):
        monkeypatch.setattr(pg.sys, 'platform', platform)
        with pytest.raises(RuntimeError, match='managed_route_linux_only'):
            gate_module.PipeWireGate().inspect_pair()
        if platform == 'win32':
            assert bridge_module.enumerate_sources() == []
        else:
            with pytest.raises(RuntimeError, match='source_bridge_linux_only'):
                bridge_module.enumerate_sources()
        with pytest.raises(RuntimeError, match='source_bridge_graph_unavailable'):
            bridge_module._read_graph()
    assert not backend.children


class SimulatedStop:
    def __init__(self, clock, limit):
        self.clock, self.limit = clock, limit
        self.delays = []
        self.done = False

    def is_set(self):
        return self.done

    def set(self):
        self.done = True

    def wait(self, delay):
        self.delays.append(delay)
        self.clock[0] = round(self.clock[0] + delay, 8)
        self.done = self.clock[0] >= self.limit
        return self.done


def simulate(monkeypatch, *, mode='ok', seconds=60, direct='converted'):
    from models.voice_conversion.process import _binding
    clock, backend = [10.0], Dumps()
    backend.mode = mode
    source = pg.GraphSource(popen=backend, clock=lambda: clock[0])
    stop = source._stop = SimulatedStop(clock, 10 + seconds)
    source._thread = SimpleNamespace(is_alive=lambda: not stop.done, join=lambda timeout: None)
    monkeypatch.setattr(pg, '_shared', source)
    monkeypatch.setattr(pg, '_remote', None)
    user = source.subscribe()
    selected = bridge_module.select_source(backend.data, 'external.source')
    sink = bridge_module._sink(backend.data)
    if direct == 'passthrough':
        backend.data.extend([
            node(20, 'vrct.source-bridge.sim.capture', 120, 'Stream/Input/Audio',
                 **{'vrct.source.bridge': 'v1', 'client.id': 30}),
            node(21, 'vrct.source-bridge.sim.playback', 121, 'Stream/Output/Audio', muted=False,
                 **{'vrct.source.bridge': 'v1', 'client.id': 30}),
            dict(type='PipeWire:Interface:Client', id=30, info={'props': {'pipewire.sec.pid': 1234}}),
            *[dict(type='PipeWire:Interface:Link', info={
                'output-node-id': a, 'input-node-id': b, 'state': 'active'})
                for a, b in [(10, 20), (21, bridge_module._node(backend.data, sink.name)['id'])]]])
    publish = source._publish
    reads = []
    def observe(*args):
        publish(*args)
        if args[1] is not None:
            gate_module.PipeWireGate().inspect_pair()
            if direct == 'converted':
                _binding(selected, wait=False)
            else:
                bridge_module._links(bridge_module._read_graph(), selected, sink, 'sim', 1234, False)
            if len(reads) % 20 == 0:
                bridge_module.microphone_devices()
            reads.append(source.read(wait=False).sequence)
    source._publish = observe
    source._work()
    user.close()
    return backend, stop, reads


def test_failed_collector_restarts_with_capped_backoff(monkeypatch):
    backend, stop, _ = simulate(monkeypatch, mode='exit', seconds=4)
    assert stop.delays == [.1, .2, .4, .8, 1.0, 1.0, 1.0]
    assert len(backend.children) == 7
    assert all(child.waited for child in backend.children)


@pytest.mark.parametrize('direct', ['converted', 'passthrough'])
def test_managed_and_direct_simulation_dumps_per_minute(monkeypatch, direct):
    backend, _, reads = simulate(monkeypatch, direct=direct)
    assert len(reads) == len(backend.children) == 600
    # Previous two independent 100 ms readers plus the 2 s device fallback.
    assert 2 * len(reads) + len(reads[::20]) == 1230


def test_mainloop_shutdown_always_closes_graph_source(shared):
    import ast
    path = Path(__file__).resolve().parents[1] / 'mainloop.py'
    module = ast.parse(path.read_text(encoding="utf-8"))
    main = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'Main')
    stop = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == 'stop')
    source, backend = shared
    user = source.subscribe()
    source.read()
    backend.mode = 'stall'
    until(lambda: len(backend.children) == 2)
    errors = []
    def broken_shutdown():
        raise RuntimeError('controller cleanup failed')
    owner = SimpleNamespace(controller=SimpleNamespace(shutdown=broken_shutdown),
                            _stop_event=Event(), _threads=[])
    namespace = dict(sys=sys, time=time, errorLogging=lambda: errors.append(True))
    exec(compile(ast.Module(body=[stop], type_ignores=[]), str(path), 'exec'), namespace)
    namespace['stop'](owner)
    assert errors == [True] and owner._stop_event.is_set()
    assert source._thread is None and backend.children[-1].killed
    user.close()


def test_stalled_dump_is_killed_then_retried_without_reusing_old_data(shared):
    source, backend = shared
    with source.subscribe():
        source.read()
        backend.mode = 'stall'
        until(lambda: len(backend.children) == 2)
        stalled = backend.children[1]
        until(lambda: source.observation().data is None)
        assert stalled.killed and stalled.waited
        with pytest.raises(pg.GraphUnavailable):
            source.read(wait=False)
        backend.mode = 'ok'
        until(lambda: source.observation().data is not None)
        assert source.read(wait=False).sequence >= 3
