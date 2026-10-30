# SPDX-License-Identifier: GPL-3.0-only
import importlib
import importlib.util
import io
import sys
from threading import Event
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def supervisor(monkeypatch):
    # Load the real supervisor logic, replacing only the Linux output boundary.
    # Do not leave an import containing a fake dependency in sys.modules.
    output = ModuleType('models.audio_routing.devices_pipewire')

    def unexpected_output(*args, **kwargs):
        pytest.fail('test must supply an output; no real PipeWire is permitted')

    output.PipeWireOutput = unexpected_output
    spec = importlib.util.find_spec('integrations.seed_vc.acceptance')
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, output.__name__, output)
        spec.loader.exec_module(module)
    return module


def test_worker_spawn_failure_releases_output_and_bridge(tmp_path, monkeypatch, supervisor):
    module = supervisor
    closed = []

    class Bridge:
        def configure(self, source):
            pass

        def close(self):
            closed.append('bridge')
            return True

    class Output:
        def __init__(self, *args):
            pass

        def close(self, **kwargs):
            closed.append('output')

    def fail(*args, **kwargs):
        raise FileNotFoundError('no worker runtime')

    monkeypatch.setattr(module, 'SourceBridge', Bridge)
    monkeypatch.setattr(module, 'PipeWireOutput', Output)
    monkeypatch.setattr(module, 'graph_snapshot', lambda: [])
    monkeypatch.setattr(module, 'select_source', lambda *args: None)
    monkeypatch.setattr(module.subprocess, 'Popen', fail)
    with pytest.raises(FileNotFoundError):
        module.WorkerRoute(tmp_path, io.BytesIO())
    assert set(closed) == {'output', 'bridge'}


@pytest.mark.parametrize('delay_at', ['receive', 'prepare', 'write'])
def test_stale_packet_never_reaches_output_after_a_stall(monkeypatch, delay_at, supervisor):
    module = supervisor
    clock = [10_000_000_000]
    due = clock[0] - (2_000_000_000 if delay_at == 'receive' else 0)
    sent, closed = [], []
    packets = iter([
        ({'state': 'ready', 'block_ms': 80}, b''),
        ({'state': 'converted', 'input_due_ns': due}, b'\1\0' * 8),
        ({'state': 'overload'}, b''),
    ])
    monkeypatch.setattr(module, 'read_packet', lambda *a, **k: next(packets))
    monkeypatch.setattr(module.time, 'monotonic_ns', lambda: clock[0])

    def connected(bridge):
        if delay_at == 'prepare':
            clock[0] += 200_000_000

    def write(pcm, token):
        if delay_at == 'write':
            clock[0] += 200_000_000
        token.check()
        sent.append(pcm)

    monkeypatch.setattr(module, 'active', connected)
    route = module.WorkerRoute.__new__(module.WorkerRoute)
    route.token = module.CancelToken()
    route.bridge = SimpleNamespace(start=lambda: None, stop=lambda: closed.append('bridge'))
    route.output = SimpleNamespace(write=write, close=lambda **kwargs: closed.append('output'))
    route.child = SimpleNamespace(stdout=None, poll=lambda: None,
                                  terminate=lambda: closed.append('worker'))
    route.ready, route.done = Event(), Event()
    route.reason = None
    route.forwarding = False
    route.packets = []
    route.pump()
    assert sent == []
    assert route.reason == 'TimeoutError' and route.done.is_set()
    assert set(closed) == {'bridge', 'output', 'worker'}


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux PipeWire pipe output uses fcntl')
def test_pipewire_rechecks_cancellation_after_writable_wait(monkeypatch):
    module = importlib.import_module('models.audio_routing.devices_pipewire')
    writable = [False]
    sent = []

    class Token:
        def check(self):
            if writable[0]:
                raise TimeoutError('packet expired while waiting')

    pipe = SimpleNamespace(fileno=lambda: 55)
    output = module.PipeWireOutput.__new__(module.PipeWireOutput)
    output.process = SimpleNamespace(poll=lambda: None, stdin=pipe)

    def select(*args):
        writable[0] = True
        return [], [pipe], []

    monkeypatch.setattr(module.select, 'select', select)
    monkeypatch.setattr(module.os, 'write', lambda fd, data: sent.append(bytes(data)) or len(data))
    with pytest.raises(TimeoutError):
        output.write(b'\1\0' * 8, Token())
    assert sent == []
