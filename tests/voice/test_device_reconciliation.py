"""Device snapshots and COM notification ordering, using memory-only substitutes."""
import ast
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from audio_device_identity import capture_key, device_id, resolve_device


@pytest.fixture
def manager():
    path = Path(__file__).parents[2] / 'src-python/device_manager.py'
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    env = dict(dataclass=dataclass, Any=Any, Callable=Callable, Dict=Dict, List=List, Optional=Optional,
        Event=Event, Lock=Lock, Thread=Thread, uuid4=uuid4,
        sys=SimpleNamespace(platform='linux'), PyAudio=None, paWASAPI=None,
        ActiveEndpointTracker=object, MMNotificationClient=object, AudioUtilities=None, comtypes=None,
        errorLogging=lambda: None, printLog=lambda *args: None,
        pyaudio_op_lock=Lock(), capture_key=capture_key, device_id=device_id)
    exec(compile(ast.Module(body=classes, type_ignores=[]), str(path), 'exec'), env)
    dm = object.__new__(env['DeviceManager'])
    dm.init()
    return dm, env


@pytest.fixture
def monitor(manager):
    dm, env = manager
    dm._stop_event.clear()
    clock = SimpleNamespace(now=0.0, waits=[])
    env['monotonic'] = lambda: clock.now
    def wait(timeout):
        clock.waits.append(timeout)
        if len(clock.waits) > 100:
            # End a broken test without ever waiting for wall-clock time.
            dm._stop_event.set()
            return False
        if dm._notify_event.is_set():
            return True
        clock.now += timeout
        return False
    dm._notify_event.wait = wait
    return dm, env, clock


def snapshot(dm, device):
    return dm._identifiedSnapshot(mic_devices={'WASAPI': [device]},
        default_mic_device={'host': {'name': 'WASAPI'}, 'device': device},
        speaker_devices=[device], default_speaker_device={'device': device})


@pytest.mark.parametrize('change', [dict(index=6), dict(defaultSampleRate=16000),
    dict(maxInputChannels=1), dict(endpoint_id='replacement')])
def test_incarnation_or_format_change_is_not_hidden_by_same_label(manager, change):
    dm, _ = manager
    original = dict(name='USB mic', index=1, endpoint_id='native-a', defaultSampleRate=48000, maxInputChannels=2)
    dm._device_snapshot = snapshot(dm, original)
    dm._applyDeviceDiffs()
    dm.noticeUpdateDevices()
    before = dm.mic_devices['WASAPI'][0]
    dm._device_snapshot = snapshot(dm, dict(original, **change))
    dm._applyDeviceDiffs()
    assert dm.update_flag_mic_device_list
    assert dm.update_flag_speaker_device_list
    assert dm.update_flag_default_mic_device
    assert dm.update_flag_default_speaker_device
    assert capture_key(before) != capture_key(dm.mic_devices['WASAPI'][0])


def test_duplicates_keep_native_ids_and_only_unambiguous_legacy_selection_migrates(manager):
    dm, _ = manager
    devices = [dict(name='USB mic', index=i, endpoint_id=key) for i, key in [(1, 'a'), (6, 'b')]]
    snap = dm._identifiedSnapshot(mic_devices={'WASAPI': devices},
        default_mic_device={'host': {'name': 'WASAPI'}, 'device': devices[1]},
        speaker_devices=[], default_speaker_device={'device': {'name': 'NoDevice'}})
    listed = snap.mic_devices['WASAPI']
    assert len({device_id(d) for d in listed}) == 2
    assert resolve_device(listed, device_id(listed[1])) == listed[1]
    assert resolve_device(listed, name='USB mic') is None
    assert resolve_device(listed[:1], name='USB mic') == listed[0]
    assert resolve_device(listed, endpoint_id='missing', name='USB mic') is None


def test_slot_only_identity_cannot_survive_replacement_or_restart(manager):
    dm, env = manager
    device = dict(name='USB mic', index=1, defaultSampleRate=48000, maxInputChannels=2)
    before = snapshot(dm, device).mic_devices['WASAPI'][0]
    callback = env['Client'](dm._notify_event, dm._invalidateDeviceIncarnations)
    callback.on_device_removed('endpoint')
    after = snapshot(dm, device).mic_devices['WASAPI'][0]
    assert device_id(before) != device_id(after)
    other = object.__new__(env['DeviceManager'])
    other.init()
    assert device_id(before) != device_id(snapshot(other, device).mic_devices['WASAPI'][0])


def test_topology_event_during_enumeration_keeps_next_incarnation_distinct(manager):
    dm, env = manager
    device = dict(name='USB mic', index=1, defaultSampleRate=48000,
                  maxInputChannels=2, isLoopbackDevice=False)
    p = MagicMock()
    p.__enter__.return_value = p
    p.get_host_api_count.return_value = 1
    p.get_host_api_info_by_index.return_value = dict(name='WASAPI', deviceCount=1)
    p.get_device_info_by_host_api_device_index.return_value = device
    p.get_default_host_api_info.return_value = dict(defaultInputDevice=1)
    env['PyAudio'] = lambda: p
    callback = env['Client'](dm._notify_event, dm._invalidateDeviceIncarnations)
    def event_after_snapshot():
        callback.on_device_removed('old-endpoint')
        return dict(defaultInputDevice=1)
    p.get_default_host_api_info.side_effect = event_after_snapshot
    dm.update()
    before = dm.mic_devices['WASAPI'][0]
    p.get_default_host_api_info.side_effect = None
    dm.update()
    after = dm.mic_devices['WASAPI'][0]
    assert before['incarnation'][0] + 1 == after['incarnation'][0]
    assert device_id(before) != device_id(after)
    assert dm._notify_event.is_set()


@pytest.mark.parametrize('notification_during_refresh', [True, False])
def test_com_events_during_snapshot_survive_and_timeouts_reconcile(monitor, notification_during_refresh):
    dm, env, clock = monitor
    com = Mock()
    enumerator = Mock()
    env['comtypes'] = com
    env['AudioUtilities'] = SimpleNamespace(GetDeviceEnumerator=lambda: enumerator)
    dm._stop_event.clear()
    dm._notify_event.set()
    snapshots = []
    def update():
        snapshots.append(clock.now)
        if len(snapshots) == 1 and notification_during_refresh:
            dm._notify_event.set()
        if len(snapshots) == 2:
            dm._stop_event.set()
    dm.update = update
    dm.monitoring()
    assert snapshots == ([0.0, 0.0] if notification_during_refresh else [0.0, 60.0])
    enumerator.RegisterEndpointNotificationCallback.assert_called_once()
    enumerator.UnregisterEndpointNotificationCallback.assert_called_once()
    com.CoInitialize.assert_called_once()
    com.CoUninitialize.assert_called_once()


def test_com_notification_refreshes_immediately_and_resets_safety_net(monitor):
    dm, env, clock = monitor
    env['comtypes'] = Mock()
    env['AudioUtilities'] = Mock()
    wait = dm._notify_event.wait
    def notify_at_ten_seconds(timeout):
        notified = wait(timeout)
        if clock.now == 10.0:
            dm._notify_event.set()
            return True
        return notified
    dm._notify_event.wait = notify_at_ten_seconds
    snapshots = []
    def update():
        snapshots.append(clock.now)
        if len(snapshots) == 3:
            dm._stop_event.set()
    dm.update = update
    dm.monitoring()
    assert snapshots == [10.0, 70.0, 130.0]
    assert set(clock.waits) == {2.0}


@pytest.mark.parametrize('registration_failed', [False, True])
def test_without_com_registration_every_two_second_timeout_refreshes(monitor, registration_failed):
    dm, env, clock = monitor
    if registration_failed:
        env['comtypes'] = Mock()
        env['AudioUtilities'] = Mock()
        env['AudioUtilities'].GetDeviceEnumerator().RegisterEndpointNotificationCallback.side_effect = OSError('COM unavailable')
    snapshots = []
    def update():
        snapshots.append(clock.now)
        if len(snapshots) == 2:
            dm._stop_event.set()
    dm.update = update
    dm.monitoring()
    assert snapshots == [2.0, 4.0]
    if registration_failed:
        env['comtypes'].CoUninitialize.assert_called_once()


@pytest.mark.parametrize('wake_notification', [False, True])
def test_stop_between_com_reconciliations_never_enumerates(monitor, wake_notification):
    dm, env, clock = monitor
    env['comtypes'] = Mock()
    env['AudioUtilities'] = Mock()
    wait = dm._notify_event.wait
    def stop_during_wait(timeout):
        dm._stop_event.set()
        if wake_notification:
            dm._notify_event.set()
        return wait(timeout)
    dm._notify_event.wait = stop_during_wait
    dm.update = Mock()
    dm.monitoring()
    dm.update.assert_not_called()
    assert clock.now == (0.0 if wake_notification else 2.0)
    env['AudioUtilities'].GetDeviceEnumerator().UnregisterEndpointNotificationCallback.assert_called_once()
    env['comtypes'].CoUninitialize.assert_called_once()


def test_speaker_peak_identity_survives_fallback_polling(manager):
    dm, _ = manager
    dm._speaker_auto_active = True
    speakers = [dict(name='USB Audio [Loopback]', endpoint_id=key, index=index)
                for key, index in [('a', 1), ('b', 6)]]
    def refresh():
        dm._device_snapshot = dm._identifiedSnapshot(mic_devices={},
            default_mic_device={'device': {'name': 'NoDevice'}}, speaker_devices=speakers,
            default_speaker_device={'device': speakers[0]})
    refresh()
    changed = []
    dm.callback_default_speaker_device = changed.append
    dm._onActiveSpeakerEndpointChanged({'id': 'b', 'name': 'USB Audio'})
    assert dm.default_speaker_device['device']['endpoint_id'] == 'b'
    refresh()
    assert dm.default_speaker_device['device']['endpoint_id'] == 'b'
    assert len(changed) == 1


def test_windows_ids_map_only_unique_labels_and_release_before_com_uninit(manager):
    dm, env = manager
    active, released = [], []
    class Endpoint:
        FriendlyName = 'USB mic'
        id = 'native'
        def __del__(self):
            released.append(bool(active))
    env['sys'] = SimpleNamespace(platform='win32')
    env['comtypes'] = SimpleNamespace(CoInitialize=lambda: active.append(True), CoUninitialize=active.clear)
    env['AudioUtilities'] = SimpleNamespace(GetAllDevices=lambda: [Endpoint()])
    assert dm._windowsEndpointIds() == {'USB mic': ['native']}
    assert released == [True]
    one = snapshot(dm, dict(name='USB mic', index=1)).mic_devices['WASAPI'][0]
    assert one['endpoint_id'] == 'native'
