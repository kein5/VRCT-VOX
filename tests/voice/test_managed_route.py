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
        return self.inspect()


@pytest.fixture
def route():
    from models.audio_routing.managed_route import VoiceRoute
    bus, gate, store = VoiceEventBus(), Gate(), Store()
    control = VoiceRoute(bus, gate=gate, store=store, poll_interval=0.01)
    yield control, bus, gate, store
    gate.release.set()
    gate.missing = gate.fail = store.fail = False
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
