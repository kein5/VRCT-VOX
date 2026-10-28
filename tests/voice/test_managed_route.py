from threading import Event

import pytest

from models.audio_routing.audio_router import AudioRouter
from models.tts.settings import VoiceSettings
from models.tts.tts_scheduler import VoiceEventBus
from models.voice_events import AudioFrame
from test_scheduler import Sink, event, until


def test_mute_latch_survives_settings_and_stop_and_resume_invalidates_muted_chat():
    class Provider:
        def __init__(self, url):
            pass

        def synthesize_stream(self, text, voice, language, token):
            yield AudioFrame(b'\x01\x00' * 48, 48000)

    sink = Sink()
    bus = VoiceEventBus(VoiceSettings(mode='original', output_device='cable'),
                        provider_factory=Provider, router=AudioRouter(lambda *a: sink))
    try:
        bus.set_muted(True)
        muted_epoch = bus.generation()
        assert not bus.publish(event('muted'))
        bus.configure(VoiceSettings(mode='original', output_device='new'))
        bus.cancel()
        assert bus.status()['muted']
        queued_during_mute = bus.generation()
        bus.set_muted(False)
        assert bus.generation() > queued_during_mute > muted_epoch
        assert not bus.publish(event('queued'), expected_generation=queued_during_mute)
        assert bus.publish(event('new'))
        until(lambda: bus.status()['completed'] == 1)
        assert len(sink.data) == 1
    finally:
        bus.close()


class Store:
    def __init__(self, muted=False):
        self.value = muted
        self.fail = False

    def read(self):
        return self.value

    def write(self, value):
        if self.fail:
            raise OSError('disk unavailable')
        self.value = value


class Gate:
    def __init__(self):
        self.identity = (123, 10)
        self.muted = False
        self.direct_identity = (123, 11)
        self.direct_muted = False
        self.direct_missing = False
        self.direct_fail = False
        self.changes = []
        self.missing = False
        self.fail = False
        self.resuming = Event()
        self.release = Event()
        self.release.set()

    def inspect(self):
        if self.missing:
            raise RuntimeError('managed_endpoint_missing')
        return {'identity': self.identity, 'muted': self.muted}

    def set_muted(self, value, expected_identity):
        if self.fail:
            raise RuntimeError('gate_control_failed')
        if not value:
            self.resuming.set()
            assert self.release.wait(2)
        if expected_identity != self.identity:
            raise RuntimeError('managed_endpoint_changed')
        self.muted = value
        self.changes.append(('main', value))
        return self.inspect()

    def inspect_pair(self):
        state = self.inspect()
        if self.direct_missing:
            raise RuntimeError('direct_endpoint_missing')
        return {'source': state,
                'direct': {'identity': self.direct_identity, 'muted': self.direct_muted}}

    def set_direct_muted(self, value, expected_identity):
        if self.direct_fail:
            raise RuntimeError('direct_gate_control_failed')
        if self.direct_missing or expected_identity != self.direct_identity:
            raise RuntimeError('direct_endpoint_changed')
        self.direct_muted = value
        self.changes.append(('direct', value))
        return self.inspect_pair()['direct']


@pytest.fixture
def route():
    from models.audio_routing.managed_route import VoiceRoute
    bus, gate, store = VoiceEventBus(), Gate(), Store()
    control = VoiceRoute(bus, gate=gate, store=store, poll_interval=0.01)
    yield control, bus, gate, store
    gate.release.set()
    gate.missing = gate.fail = store.fail = False
    gate.direct_missing = gate.direct_fail = False
    control.close()
    bus.close()


def ready(control):
    until(lambda: control.status()['ready'] and not control.status()['pending'])


def test_managed_start_mutes_and_settings_refresh_cannot_unmute(route):
    control, bus, gate, store = route
    control.configure(True)
    ready(control)
    assert gate.muted and store.value and bus.status()['muted']
    control.configure(True)
    assert control.status()['observed_muted'] is True
    control.resume()
    ready(control)
    assert not gate.muted and not store.value and not bus.status()['muted']
    control.configure(True)
    assert not control.status()['requested_muted']  # Reapplying mode does not invent a new decision.


def test_stale_resume_never_opens_bus_after_new_mute(route):
    control, bus, gate, store = route
    control.configure(True)
    ready(control)
    gate.release.clear()
    control.resume()
    assert gate.resuming.wait(1)
    control.mute()
    gate.release.set()
    ready(control)
    assert gate.muted and store.value and bus.status()['muted']


def test_identity_replacement_requires_another_explicit_resume(route):
    control, bus, gate, store = route
    control.configure(True)
    ready(control)
    control.resume()
    ready(control)
    gate.identity = (456, 10)  # Same serial reused after daemon restart.
    gate.muted = True
    until(lambda: control.status()['requested_muted'])
    ready(control)
    assert gate.muted and bus.status()['muted'] and store.value


@pytest.mark.parametrize('failure', ['missing', 'fail', 'storage'])
def test_failed_control_never_claims_ready_and_keeps_software_closed(route, failure):
    control, bus, gate, store = route
    if failure == 'storage':
        store.fail = True
    else:
        setattr(gate, failure, True)
    control.configure(True)
    until(lambda: control.status()['error'])
    assert not control.status()['ready']
    assert bus.status()['muted']
    with pytest.raises(RuntimeError):
        control.resume()


def test_leaving_managed_route_requires_confirmed_mute(route):
    control, bus, gate, store = route
    control.configure(True)
    ready(control)
    control.resume()
    ready(control)
    gate.fail = True
    with pytest.raises(RuntimeError):
        control.configure(False, timeout=0.1)
    assert control.status()['managed']
    assert bus.status()['muted']
    gate.fail = False
    ready(control)
    control.configure(False)
    assert not control.status()['managed'] and gate.muted and store.value


def test_saved_latch_survives_control_recreation():
    from models.audio_routing.managed_route import VoiceRoute
    store = Store(True)
    bus = VoiceEventBus()
    control = VoiceRoute(bus, gate=Gate(), store=store)
    try:
        assert bus.status()['muted']
        control.resume()
        ready(control)
        assert not store.value and not bus.status()['muted']
    finally:
        control.close()
        bus.close()


@pytest.mark.parametrize("lost_confirmation", [False, True])
def test_close_drains_late_resume_before_reporting_confirmed_shutdown(route, lost_confirmation):
    from threading import Thread
    control, bus, gate, store = route
    control.configure(True)
    ready(control)
    if lost_confirmation:
        original = gate.set_muted
        def apply_without_confirmation(value, identity):
            state = original(value, identity)
            if not value:
                raise RuntimeError('confirmation_lost_after_unmute')
            return state
        gate.set_muted = apply_without_confirmation
    gate.release.clear()
    control.resume()
    assert gate.resuming.wait(1)
    results = []
    closing = Thread(target=lambda: results.append(control.close(timeout=0.05)))
    closing.start()
    # Release after the initial shutdown wait, while its old implementation joins.
    import time
    time.sleep(0.075)
    gate.release.set()
    closing.join(1)
    until(lambda: not control._thread.is_alive())
    assert gate.muted, 'a delayed resume must not outlive the final mute obligation'
    assert store.value and bus.status()['muted']
    assert control.close() is True
    assert control.status()['observed_muted'] is True
    assert not control.status()['pending']


def test_shutdown_os_failure_is_not_reported_as_confirmed_shutdown(route):
    control, bus, gate, store = route
    control.configure(True)
    ready(control)
    control.resume()
    ready(control)
    gate.fail = True
    assert control.close(timeout=.05) is False
    until(lambda: not control._thread.is_alive())
    assert not control.status()['ready'] and control.status()['pending']
    assert control.status()['error']


def test_status_orders_every_snapshot_including_same_generation_and_recreation():
    from models.audio_routing.managed_route import VoiceRoute
    bus = VoiceEventBus()
    control = VoiceRoute(bus, gate=Gate(), store=Store())
    replacement = None
    try:
        first, second = control.status(), control.status()
        assert first['generation'] == second['generation']
        assert int(first['observation_id']) < int(second['observation_id'])
        replacement = VoiceRoute(bus, gate=Gate(), store=Store())
        assert int(replacement.status()['observation_id']) > int(second['observation_id'])
    finally:
        if replacement:
            replacement.close()
        control.close()
        bus.close()


def test_direct_suppression_closes_main_first_and_policy_change_requires_resume(route):
    control, bus, gate, store = route
    control.configure(True, suppress_direct=True)
    ready(control)
    assert gate.changes == [('main', True), ('direct', True)]
    assert control.status()['requested_direct_suppressed'] is True
    assert control.status()['observed_direct_suppressed'] is True
    control.resume()
    ready(control)
    assert not gate.muted and gate.direct_muted and not bus.status()['muted']
    gate.changes.clear()
    control.configure(True, suppress_direct=False)
    ready(control)
    assert gate.changes == [('main', True), ('direct', False)]
    assert gate.muted and store.value and bus.status()['muted']
    control.resume()
    ready(control)
    assert not gate.muted and not gate.direct_muted


@pytest.mark.parametrize('fault', ['drift', 'replacement', 'missing', 'control'])
def test_direct_fault_revokes_resume_and_mutes_main_before_repair(route, fault):
    control, bus, gate, store = route
    control.configure(True, suppress_direct=True)
    ready(control)
    control.resume()
    ready(control)
    gate.changes.clear()
    if fault == 'replacement':
        gate.direct_identity = (123, 12)
    if fault == 'missing':
        gate.direct_missing = True
    else:
        gate.direct_muted = False
        gate.direct_fail = fault == 'control'
    until(lambda: control.status()['requested_muted'])
    until(lambda: gate.muted)
    assert gate.changes[0] == ('main', True)
    assert bus.status()['muted']
    if fault in ('missing', 'control'):
        until(lambda: control.status()['error'])
        assert not control.status()['ready']
        with pytest.raises(RuntimeError):
            control.resume()
    gate.direct_fail = gate.direct_missing = False
    ready(control)
    assert gate.direct_muted and gate.muted and store.value
