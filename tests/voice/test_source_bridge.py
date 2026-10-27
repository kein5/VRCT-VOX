"""Source route control: identity loss, fail-closed health, and stop races."""
import copy
import importlib
import os
import threading
import time

import pytest


def module():
    return importlib.import_module('models.audio_routing.source_bridge')


def node(ident, name, media, serial, **props):
    return {'type': 'PipeWire:Interface:Node', 'id': ident, 'info': {
        'props': {'node.name': name, 'media.class': media, 'object.serial': serial, **props},
        'params': {'Props': [{'mute': True}]}}}


def graph():
    return [{'type': 'PipeWire:Interface:Core', 'info': {'cookie': 42}},
            node(10, 'external.source', 'Audio/Source', 110),
            node(11, 'vrct.managed.vc', 'Audio/Sink', 111, **{'vrct.managed.route': 'v1'})]


def until(predicate, seconds=2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.002)
    raise AssertionError('condition did not become true')


@pytest.mark.parametrize('fault', ['absent', 'duplicate', 'class', 'feedback', 'cookie', 'serial'])
def test_selection_rejects_unsafe_or_ambiguous_source(fault):
    m = module()
    data = graph()
    name = 'external.source'
    if fault == 'absent':
        data.pop(1)
    elif fault == 'duplicate':
        data.append(copy.deepcopy(data[1]))
    elif fault == 'class':
        data[1]['info']['props']['media.class'] = 'Audio/Sink'
    elif fault == 'feedback':
        name = data[1]['info']['props']['node.name'] = 'vrct.managed.source'
    elif fault == 'cookie':
        data[0]['info']['cookie'] = True
    else:
        data[1]['info']['props']['object.serial'] = '110'
    with pytest.raises(RuntimeError):
        m.select_source(data, name)


class Child:
    def __init__(self, pid):
        self.pid, self.code = pid, None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15

    def kill(self):
        self.code = -9

    def wait(self, timeout):
        return self.code


class Backend:
    def __init__(self):
        self.data = graph()
        self.children, self.unmutes = [], []
        self.query_error = False
        self.fault = None
        self.enter = threading.Event()
        self.release = threading.Event()
        self.block_at = None

    def read(self):
        if self.query_error:
            raise RuntimeError('graph_unavailable')
        return copy.deepcopy(self.data)

    def block(self, where):
        if self.block_at == where:
            self.enter.set()
            assert self.release.wait(3)

    def launch(self, source, sink, tag):
        self.block('launch')
        child = Child(1234 + len(self.children))
        self.children.append(child)
        self.data = self.data[:3]
        for ident, suffix, media, serial in [(20, 'capture', 'Stream/Input/Audio', 120),
                                           (21, 'playback', 'Stream/Output/Audio', 121)]:
            props = {'vrct.source.bridge': 'v1', 'client.id': 30}
            self.data.append(node(ident, f'vrct.source-bridge.{tag}.{suffix}', media, serial, **props))
        self.data.extend([{'type': 'PipeWire:Interface:Link', 'info': {
            'output-node-id': a, 'input-node-id': b, 'state': 'active'}} for a, b in [(10, 20), (21, 11)]])
        if self.fault == 'missing_link':
            self.data.pop()
        elif self.fault == 'wrong_link':
            self.data[-1]['info']['input-node-id'] = 99
        elif self.fault == 'extra_link':
            self.data.append({'type': 'PipeWire:Interface:Link', 'info': {
                'output-node-id': 99, 'input-node-id': 20, 'state': 'active'}})
        elif self.fault == 'owner':
            self.data[4]['info']['props']['client.id'] = 999
        self.data.append({'id': 30, 'type': 'PipeWire:Interface:Client',
                          'info': {'props': {'pipewire.sec.pid': child.pid}}})
        return child

    def unmute(self, endpoint, tag):
        self.block('unmute')
        self.unmutes.append((endpoint, tag))
        self.data[4]['info']['params']['Props'][0]['mute'] = False


@pytest.fixture
def system(monkeypatch):
    m, backend = module(), Backend()
    monkeypatch.setattr(m.sys, 'platform', 'linux')  # fake backend, including on Windows CI
    monkeypatch.setattr(m, '_read_graph', backend.read)
    monkeypatch.setattr(m, '_launch', backend.launch)
    monkeypatch.setattr(m, '_unmute', backend.unmute)
    monkeypatch.setattr(m, 'START_TIMEOUT', .06)
    monkeypatch.setattr(m, 'MONITOR_INTERVAL', .005)
    bridge = m.SourceBridge()
    yield m, backend, bridge
    backend.release.set()
    assert bridge.close(3)


def test_default_and_configuration_never_open_audio(system):
    m, b, bridge = system
    assert bridge.health() == {'requested': False, 'active': False, 'pending': False,
                               'error': None, 'generation': 0, 'conversion_verified': False}
    bridge.configure(m.select_source(b.data, 'external.source'))
    assert not b.children and not b.unmutes
    bridge.start()
    until(lambda: bridge.health()['active'])
    assert len(b.children) == len(b.unmutes) == 1
    assert not bridge.health()['conversion_verified']
    bridge.start()  # idempotent while already requested
    assert len(b.children) == 1
    bridge.stop()
    assert not bridge.health()['requested'] and not bridge.health()['active']
    assert b.children[0].poll() is not None


@pytest.mark.parametrize('fault', ['missing_link', 'wrong_link', 'extra_link', 'owner'])
def test_never_unmute_before_complete_owned_links(system, fault):
    m, b, bridge = system
    b.fault = fault
    bridge.configure(m.select_source(b.data, 'external.source'))
    bridge.start()
    until(lambda: bridge.health()['error'])
    assert not bridge.health()['active'] and not b.unmutes
    until(lambda: b.children[0].poll() is not None)


@pytest.mark.parametrize('fault', ['epoch', 'source_serial', 'sink_serial', 'missing_source', 'link', 'query', 'process', 'mute'])
def test_active_route_closes_on_loss_and_never_auto_resumes(system, fault):
    m, b, bridge = system
    selected = m.select_source(b.data, 'external.source')
    bridge.configure(selected)
    bridge.start()
    until(lambda: bridge.health()['active'])
    if fault == 'epoch':
        b.data[0]['info']['cookie'] += 1
    elif fault.endswith('serial'):
        b.data[1 if fault == 'source_serial' else 2]['info']['props']['object.serial'] += 1
    elif fault == 'missing_source':
        b.data.pop(1)
    elif fault == 'link':
        del b.data[-2]
    elif fault == 'query':
        b.query_error = True
    elif fault == 'process':
        b.children[0].code = 1
    else:
        b.data[4]['info']['params']['Props'][0]['mute'] = True
    until(lambda: bridge.health()['error'])
    until(lambda: b.children[0].poll() is not None)
    assert not bridge.health()['requested'] and not bridge.health()['active']
    assert bridge.close()
    b.data, b.query_error = graph(), False
    time.sleep(.03)
    assert len(b.children) == 1
    bridge.configure(selected)
    bridge.start()
    until(lambda: bridge.health()['active'])
    assert len(b.children) == 2


@pytest.mark.parametrize('where', ['launch', 'unmute'])
def test_stop_invalidates_blocked_work_and_blocks_overlap(system, where):
    m, b, bridge = system
    bridge.configure(m.select_source(b.data, 'external.source'))
    b.block_at = where
    bridge.start()
    assert b.enter.wait(1)
    before = time.monotonic()
    bridge.stop()
    assert time.monotonic() - before < .1
    with pytest.raises(RuntimeError, match='stopping'):
        bridge.start()
    if where == 'unmute':
        assert b.children[0].poll() is not None
    b.release.set()
    assert bridge.close()
    assert not bridge.health()['active'] and not bridge.health()['error']
    assert all(c.poll() is not None for c in b.children)
    if where == 'launch':
        assert not b.unmutes
    old_tags = [tag for _, tag in b.unmutes]
    b.block_at = None
    bridge.start()
    until(lambda: bridge.health()['active'])
    assert b.unmutes[-1][1] not in old_tags


def test_reselected_source_and_non_linux_are_rejected_before_launch(system, monkeypatch):
    m, b, bridge = system
    bridge.configure(m.select_source(b.data, 'external.source'))
    b.data[1]['info']['props']['object.serial'] += 1
    bridge.start()
    until(lambda: bridge.health()['error'])
    assert not b.children
    assert bridge.close()
    monkeypatch.setattr(m.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='linux_only'):
        bridge.start()
    assert not b.children


def test_launch_arguments_pin_serials_and_start_muted(monkeypatch):
    m = module()
    captured = []
    class Supervisor(Child):
        stdout = open(os.devnull, 'rb')
    def launch(args, **kw):
        captured.append((args, kw))
        return Supervisor(1234)
    monkeypatch.setattr(m.subprocess, 'Popen', launch)
    monkeypatch.setattr(m, '_audio_pid', lambda process: 1235)
    monkeypatch.setattr(m.os, 'pidfd_open', lambda *args: os.open(os.devnull, os.O_RDONLY), raising=False)
    m._launch(m.Endpoint(42, 110, 'external.source', 'Audio/Source'),
              m.Endpoint(42, 111, 'vrct.managed.vc', 'Audio/Sink'), 'a' * 32)
    args, kwargs = captured[0]
    assert args[0].endswith('vrct-source-bridge')
    capture, playback = args[args.index('--capture-props') + 1], args[args.index('--playback-props') + 1]
    assert 'target.object=110' in capture and 'target.object=111' in playback
    assert 'node.param.Props={mute=true}' in playback
    for value in (capture, playback):
        assert all(x in value for x in ['node.dont-fallback=true', 'node.dont-reconnect=true',
                                       'node.dont-move=true', 'node.linger=false'])
    assert not kwargs.get('shell', False)
    assert kwargs['pass_fds'] == (int(args[2]),)


@pytest.mark.parametrize('fault', [None, 'missing', 'duplicate', 'wrong_pid', 'spoof_app_pid'])
def test_stream_owner_is_the_server_authenticated_client(fault):
    m, b = module(), Backend()
    source = m.select_source(b.data, 'external.source')
    sink = m.Endpoint(42, 111, 'vrct.managed.vc', 'Audio/Sink')
    tag = 'b' * 32
    child = b.launch(source, sink, tag)
    b.data.pop()  # Replace the client's credentials with each fault case.
    for item in b.data[3:5]:
        props = item['info']['props']
        props['client.id'] = 30
    client = {'id': 30, 'type': 'PipeWire:Interface:Client', 'info': {'props': {
        'pipewire.sec.pid': child.pid, 'application.process.id': child.pid}}}
    if fault in ('wrong_pid', 'spoof_app_pid'):
        client['info']['props']['pipewire.sec.pid'] = 999
    if fault == 'spoof_app_pid':
        for item in b.data[3:5]:
            item['info']['props']['application.process.id'] = child.pid
    if fault != 'missing':
        b.data.append(client)
    if fault == 'duplicate':
        b.data.append(copy.deepcopy(client))
    if fault is None:
        assert m._links(b.data, source, sink, tag, child.pid, True).serial == 121
    else:
        with pytest.raises(RuntimeError, match='owner'):
            m._links(b.data, source, sink, tag, child.pid, True)


def test_kernel_without_thread_pidfd_rejects_start_without_spawning(monkeypatch):
    m = module()
    def unavailable(*args):
        raise OSError('unsupported')
    monkeypatch.setattr(m.os, 'pidfd_open', unavailable, raising=False)
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must not spawn'))
    with pytest.raises(RuntimeError, match='thread_watch_unavailable'):
        m._launch(m.Endpoint(42, 110, 'external.source', 'Audio/Source'),
                  m.Endpoint(42, 111, 'vrct.managed.vc', 'Audio/Sink'), 'a' * 32)
