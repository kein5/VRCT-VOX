"""Converted monitor mute, with fake devices/inference and in-process control peers."""
from contextlib import contextmanager
import os
from threading import Event, Thread
import time
import sys
from types import SimpleNamespace

import pytest

if sys.platform != 'linux':
    # The managed route and the VC transport (process -> devices_pipewire) are Linux only.
    pytest.skip('Linux managed route and VC transport', allow_module_level=True)

from models.audio_routing.monitor_output import MonitorTee
from models.voice_conversion import direct_voice, isolated, process, router_worker
from models.voice_conversion.router_protocol import BASE_STATE, encode, validate_health, validate_monitor_control
from tools.voice_acceptance import wait_for

from test_controller_integration import controller_module  # noqa: F401
from test_direct_voice_controller import ConvertedBackend, app, managed, request  # noqa: F401
from test_managed_route import ready
from test_monitor_vc import SEED, SINK, SOURCE

MONITOR = {'device': 'test.speakers', 'volume': 100}


@pytest.mark.parametrize('blocked_at', ['open', 'write'])
def test_mute_discards_queued_and_inflight_monitor_audio_and_resumes_only_new_audio(monkeypatch, blocked_at):
    entered, release = Event(), Event()
    writes, closes, tees = [], [], []

    class Output:
        def write(self, pcm, token):
            if blocked_at == 'write' and not release.is_set():
                entered.set()
                assert release.wait(2)
            token.commit_audio_write(pcm, lambda: writes.append(pcm))

        def close(self, *, drain, token):
            closes.append(drain)

    def open_output(*args, **kwargs):
        if blocked_at == 'open' and not release.is_set():
            entered.set()
            assert release.wait(2)
        return Output()

    def tee(*args, **kwargs):
        item = MonitorTee(*args, output_factory=open_output, **kwargs)
        tees.append(item)
        return item

    monkeypatch.setattr(process, 'MonitorTee', tee)
    vc = process.VCProcess(engine='rvc', monitor=MONITOR)
    worker = vc._child = object()  # No conversion process is launched.
    token = vc._token
    vc._requested = vc._active = True
    vc._open_monitor(SINK)
    try:
        vc._offer_monitor(b'\1\0', time.monotonic_ns())
        assert not tees  # Starting while muted never opens a monitor device.
        vc.set_monitor_muted(False)
        old_stamp = time.monotonic_ns()
        vc._offer_monitor(b'\2\0', old_stamp)
        assert entered.wait(1)
        vc._offer_monitor(b'\3\0', time.monotonic_ns())
        vc._offer_monitor(b'\4\0', time.monotonic_ns())
        vc.set_monitor_muted(True)
        assert not tees[0]._queue and tees[0]._token.is_set()
        vc._offer_monitor(b'\5\0', time.monotonic_ns())
        vc.set_monitor_muted(False)
        # An old device still opening/writing cannot overlap a new monitor.
        vc._offer_monitor(b'\6\0', time.monotonic_ns())
        assert len(tees) == 1
        release.set()
        assert tees[0].join(1)
        assert writes == [] and closes == [False]
        vc._offer_monitor(b'\7\0', old_stamp)  # Inference started before resume.
        assert len(tees) == 1
        vc._offer_monitor(b'\10\0', time.monotonic_ns())
        wait_for(lambda: writes == [b'\10\0'])
        assert len(tees) == 2
        assert vc._child is worker and vc._token is token and not token.is_set()
        assert vc.health()['requested'] and vc.health()['active']
    finally:
        release.set()
        vc._stop_monitor()


@contextmanager
def control_peer(monkeypatch, *, muted=True, fault=None):
    """Real owner/router protocol over anonymous pipes; no OS audio or child process."""
    from models.audio_routing import pipewire_graph_pipe
    monkeypatch.setattr(pipewire_graph_pipe, 'receive_from_parent', lambda: None)
    monkeypatch.setattr(direct_voice, 'create_worker_process', lambda options: None)
    commands, started, closed = [], Event(), Event()

    class Backend:
        def set_monitor_muted(self, value):
            commands.append(value)

        def start(self, *, source):
            started.set()

        def health(self):
            return dict(BASE_STATE, requested=True, active=True, state='ready')

        def close(self, timeout):
            closed.set()
            return True

    monkeypatch.setattr(router_worker, 'create_worker_process', lambda *args, **kwargs: Backend())
    owner_read, owner_write = os.pipe()
    reply_read, reply_write = os.pipe()
    incoming, outgoing = os.fdopen(owner_read, 'rb', buffering=0), os.fdopen(reply_write, 'wb', buffering=0)
    monkeypatch.setattr(router_worker, 'sys', SimpleNamespace(
        stdin=SimpleNamespace(buffer=incoming, fileno=incoming.fileno),
        stdout=SimpleNamespace(buffer=outgoing, fileno=outgoing.fileno)))

    class Child:
        def __init__(self):
            self.stdin = os.fdopen(owner_write, 'wb', buffering=0)
            self.stdout = os.fdopen(reply_read, 'rb', buffering=0)
            self.result = None
            self.thread = Thread(target=self.run, daemon=True)

        def run(self):
            try:
                self.result = router_worker.main()
            finally:
                incoming.close()
                outgoing.close()

        def wait(self, timeout):
            self.thread.join(timeout)
            assert not self.thread.is_alive()
            return self.result

    child = Child()

    def launch(source):
        child.thread.start()
        return child

    monkeypatch.setattr(isolated, '_launch', launch)
    owner = isolated.IsolatedVCProcess(SEED, monitor=MONITOR)
    owner.set_monitor_muted(muted)
    owner.start(source=SOURCE)
    try:
        assert started.wait(1)
        wait_for(lambda: owner.health()['active'])
        if fault:
            write = os.write
            control_fd = child.stdin.fileno()

            def broken_write(fd, data):
                if fd == control_fd:
                    if fault == 'full':
                        raise BlockingIOError
                    if fault == 'lost':
                        return len(data)  # Peer keeps sending health but never applies the command.
                    raise BrokenPipeError
                return write(fd, data)
            monkeypatch.setattr(isolated.os, 'write', broken_write)
        yield owner, child, commands, closed
    finally:
        assert owner.close(timeout=3)


def test_owner_sends_initial_mute_and_live_updates_without_restarting(monkeypatch):
    with control_peer(monkeypatch) as (owner, child, commands, closed):
        assert commands == [True]
        owner.set_monitor_muted(False)
        wait_for(lambda: owner.health()['monitor_revision'] == 1)
        assert commands == [True, False]
        owner.set_monitor_muted(True)
        wait_for(lambda: owner.health()['monitor_revision'] == 2)
        assert commands == [True, False, True]
        assert owner._child is child and owner.health()['requested'] and not closed.is_set()
        owner.set_monitor_muted(False)
        wait_for(lambda: owner.health()['monitor_revision'] == 3)
        assert commands[-1] is False and not owner._stop.is_set()
    assert closed.is_set()


def test_owner_coalesced_mute_resume_still_advances_the_monitor_boundary(monkeypatch):
    with control_peer(monkeypatch, muted=False) as (owner, child, commands, closed):
        assert commands == [False]
        with owner._lock:  # Hold the sender so both edges happen before delivery.
            owner._monitor_muted, owner._monitor_revision = True, 2
            owner._monitor_muted, owner._monitor_revision = False, 3
        wait_for(lambda: owner.health()['monitor_revision'] == 3)
        assert commands == [False, False]  # Worker rotates the tee even for the same final value.
        assert owner._child is child and not closed.is_set()


@pytest.mark.parametrize('fault,code', [('broken', 'vc_router_failed'),
                                      ('full', 'vc_router_timeout'), ('lost', 'vc_router_timeout')])
def test_failed_mute_delivery_reports_existing_error_and_closes_the_peer(monkeypatch, fault, code):
    with control_peer(monkeypatch, muted=False, fault=fault) as (owner, child, commands, closed):
        owner.set_monitor_muted(True)
        wait_for(lambda: owner.health()['error'] is not None, timeout=3)
        assert owner.health()['error'] == code
        wait_for(closed.is_set)
        assert commands == [False]  # The missing mute was not mistaken for acknowledgement.


@pytest.mark.parametrize('value', [None, {}, {'kind': 'monitor_mute', 'muted': 1, 'revision': 1},
    {'kind': 'monitor_mute', 'muted': True, 'revision': True},
    {'kind': 'monitor_mute', 'muted': True, 'revision': -1},
    {'kind': 'monitor_mute', 'muted': True, 'revision': 2**63}])
def test_monitor_control_rejects_invalid_frames(value):
    with pytest.raises(ValueError, match='vc_router_request_invalid'):
        validate_monitor_control(value)


def test_health_rejects_invalid_monitor_acknowledgement():
    state = dict(BASE_STATE, kind='health', sent_ns=time.monotonic_ns())
    for revision in (-1, True, 2**63, '1'):
        with pytest.raises(ValueError, match='vc_router_health_invalid'):
            validate_health(dict(state, monitor_revision=revision))


def test_stop_during_launch_does_not_start_capture(monkeypatch):
    from models.audio_routing import pipewire_graph_pipe
    monkeypatch.setattr(pipewire_graph_pipe, 'receive_from_parent', lambda: None)
    monkeypatch.setattr(router_worker, 'create_worker_process', lambda *a, **kw: pytest.fail('started'))
    read, write = os.pipe()
    with os.fdopen(read, 'rb', buffering=0) as incoming:
        monkeypatch.setattr(router_worker, 'sys', SimpleNamespace(stdin=SimpleNamespace(buffer=incoming)))
        os.write(write, encode(dict(kind='start', source={}, options=SEED, monitor=MONITOR)))
        os.close(write)
        assert router_worker.main() == 0


def test_controller_waits_for_resume_confirmation_and_keeps_both_switches(app, monkeypatch):  # noqa: F811
    c, _, gate, _ = app
    backend = ConvertedBackend()
    monkeypatch.setattr(isolated, 'IsolatedVCProcess', lambda *args, **kwargs: backend)
    managed(c)
    assert c.setVoiceSettings(dict(c.voice_events.settings.to_dict(), monitor='on'))['status'] == 200
    assert c.startDirectVoice({**request(c), 'mode': 'converted', 'options': SEED})['status'] == 200
    assert backend.monitor_muted and gate.muted
    generation = c.direct_voice.health()['generation']
    assert c.resumeVoice()['status'] == 200
    ready(c.voice_route)
    assert not backend.monitor_muted and not gate.muted
    assert c.voice_events.set_enabled(True)
    assert c.muteVoice()['status'] == 200
    ready(c.voice_route)
    assert backend.monitor_muted and gate.muted
    assert c.voice_events.status()['tts_enabled']
    assert c.direct_voice.health()['generation'] == generation
    assert c.direct_voice.health()['requested'] and backend.state['active']
    gate.resuming.clear()
    gate.release.clear()
    try:
        assert c.resumeVoice()['status'] == 200
        assert gate.resuming.wait(1)
        assert backend.monitor_muted and c.voice_events.status()['muted']
    finally:
        gate.release.set()
    ready(c.voice_route)
    assert not backend.monitor_muted
    assert c.direct_voice._backend is backend and c.direct_voice.health()['generation'] == generation
    c.stopVoice()
    assert not backend.monitor_muted and backend.state['active']


def test_external_route_cannot_start_converted_voice_or_touch_the_os_gate(app, monkeypatch):  # noqa: F811
    c, raw, gate, _ = app
    monkeypatch.setattr(isolated, 'IsolatedVCProcess', lambda *a, **kw: pytest.fail('started'))
    assert c.voice_events.settings.routing == 'external'
    result = c.startDirectVoice({**request(c), 'mode': 'converted', 'options': SEED})
    assert result == {'status': 409, 'result': {'error_code': 'source_bridge_managed_required'}}
    c.muteVoice()
    ready(c.voice_route)
    assert c.voice_events.status()['muted'] and not raw.children and gate.changes == []
    c.resumeVoice()
    ready(c.voice_route)
    assert not c.voice_events.status()['muted'] and gate.changes == []


def test_gate_failure_also_mutes_monitor_without_disabling_conversion(app, monkeypatch):  # noqa: F811
    c, _, gate, _ = app
    backend = ConvertedBackend()
    monkeypatch.setattr(isolated, 'IsolatedVCProcess', lambda *a, **kw: backend)
    managed(c)
    assert c.setVoiceSettings(dict(c.voice_events.settings.to_dict(), monitor='on'))['status'] == 200
    c.startDirectVoice({**request(c), 'mode': 'converted', 'options': SEED})
    c.resumeVoice()
    ready(c.voice_route)
    assert not backend.monitor_muted
    try:
        gate.missing = True
        wait_for(lambda: c.voice_route.status()['error'] is not None)
        assert backend.monitor_muted
        assert c.direct_voice.health()['requested'] and c.direct_voice.health()['active']
        assert c.resumeVoice()['status'] == 409
    finally:
        gate.missing = False
    ready(c.voice_route)
    assert backend.monitor_muted  # Recovery alone cannot authorize resume.
