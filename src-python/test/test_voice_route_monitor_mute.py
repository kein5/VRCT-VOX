"""Route confirmation also gates the converted monitor, without OS services."""
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from models.audio_routing.managed_route import VoiceRoute


def test_saved_mute_reaches_monitor_before_any_start_and_resume_waits_for_persistence():
    entered, release, resumed = Event(), Event(), Event()
    calls = []

    def write(muted):
        entered.set()
        assert release.wait(2)

    def monitor(muted):
        calls.append(muted)
        if not muted:
            resumed.set()

    bus = Mock()
    route = VoiceRoute(bus, gate=None, store=SimpleNamespace(read=lambda: True, write=write),
                       on_muted=monitor)
    try:
        assert calls == [True]
        route.resume()
        assert entered.wait(1)
        assert calls == [True, True] and route.status()['pending']
        release.set()
        assert resumed.wait(1)
        assert calls == [True, True, False]
        assert not route.status()['pending']
        bus.set_muted.assert_called_with(False)
    finally:
        release.set()
        assert route.close()


def test_failed_persistence_never_reopens_monitor():
    failed = Event()
    calls = []

    def write(muted):
        failed.set()
        raise OSError('test storage failure')

    route = VoiceRoute(Mock(), gate=None, store=SimpleNamespace(read=lambda: True, write=write),
                       on_muted=calls.append)
    try:
        route.resume()
        assert failed.wait(1)
    finally:
        # Join the control thread before inspecting the error branch.
        assert not route.close()
    assert calls and all(calls)
    assert route.status()['error'] == 'mute_state_unavailable'


def test_saved_unmuted_state_is_forwarded_without_creating_a_gate_worker():
    monitor = Mock()
    route = VoiceRoute(Mock(), gate=None, store=SimpleNamespace(read=lambda: False), on_muted=monitor)
    try:
        monitor.assert_called_once_with(False)
        assert route._thread is None
    finally:
        assert route.close()
    monitor.assert_called_with(True)
